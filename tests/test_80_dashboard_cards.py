"""
Dashboard cards – end-to-end tests.

Tests:
  - Creating a cell card via the API (POST /budget/dashboard/cards/)
  - Creating a bar-chart card via the API
  - Data endpoint returns card with computed value
  - Updating a card's YAML via PATCH
  - Reordering cards via POST /reorder/
  - Resizing a card via PATCH /resize/
  - Deleting a card via DELETE
  - YAML validation errors return 400
  - Sandboxed Python cell (method=custom)
  - Presets endpoint returns items
  - Dashboard page renders (browser smoke test)
  - Dashboard add-card dialog opens and creates a card (browser)
  - Edit and delete via browser modal
  - Sequential preset clicks load without confirm dialog (test_27)
  - Dirty editor: confirm appears on preset load; cancel keeps content (test_28)
  - Dirty editor: confirm appears on preset load; overwrite loads preset (test_29)
  - Empty editor loads preset without confirm dialog (test_30)
  - Delete card via browser modal with confirmDialog (test_31)
  - Cell link navigates to the configured URL on click (test_32)
  - Cell template field renders correct text in card body (test_34)
  - Sandbox security: AST-level import/dunder blocks (TestSandboxSecurity sb_01–sb_06)
  - Sandbox security: runtime NameError for dangerous builtins (sb_07–sb_12)
  - Sandbox security: __builtins__ is empty dict, not real builtins (sb_13)
  - Sandbox security: type coercion and error handling (sb_14–sb_17)
  - Sandbox security: data isolation and SQL injection in query helpers (sb_18–sb_19)
  - method=total cell: income/savings_wit count as negative (test_13)
  - flip_signs: true inverts computed cell value (test_14)
  - bar-chart with method=total (test_15)
  - chart rejects method=count/custom with 400 (test_16)
"""
import time

import requests

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from conftest import BASE_URL, _url, session_cookies, wait_text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CARDS_URL   = BASE_URL + "/budget/dashboard/cards/"
REORDER_URL = BASE_URL + "/budget/dashboard/cards/reorder/"
PRESETS_URL = BASE_URL + "/budget/dashboard/cards/presets/"


def _cards_session(driver) -> requests.Session:
    """Return a requests Session carrying the browser's session cookie."""
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


def _csrf(sess: requests.Session) -> str:
    return next((c.value for c in sess.cookies if c.name == "csrftoken"), "")


def _post_card(sess, csrf, yaml_str) -> requests.Response:
    return sess.post(
        CARDS_URL,
        json={"yaml_config": yaml_str},
        headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
    )


def _sandbox_yaml(code: str) -> str:
    """Wrap a Python snippet in a valid method=custom cell card YAML."""
    indented = "\n".join("  " + line for line in code.splitlines())
    return (
        "type: cell\n"
        "title: SandboxTest\n"
        "method: custom\n"
        "python: |\n"
        f"{indented}\n"
        "positioning:\n"
        "  position: 99\n"
        "  width: 1\n"
        "  height: 1\n"
    )


def _sandbox_post(driver, code: str) -> dict:
    """POST a sandbox card, delete it immediately, return the card dict."""
    sess = _cards_session(driver)
    csrf = _csrf(sess)
    r = _post_card(sess, csrf, _sandbox_yaml(code))
    assert r.status_code == 201, r.text
    card = r.json()["card"]
    if card.get("id"):
        sess.delete(
            CARDS_URL.rstrip("/") + f"/{card['id']}/",
            headers={"X-CSRFToken": csrf},
        )
    return card


def _cm_text(driver, backdrop_id: str) -> str:
    """Return the text content of the CodeMirror 6 editor inside the given backdrop element."""
    return driver.execute_script(
        "const el = document.querySelector('#' + arguments[0] + ' .cm-content');"
        "return el ? el.textContent : '';",
        backdrop_id,
    )


def _set_cm_text(driver, backdrop_id: str, text: str):
    """Replace the CodeMirror editor content AND the Alpine data property that saveAdd/saveEdit reads."""
    driver.execute_script(
        """
        const data = document.querySelector('[x-data="dashboardBoard"]')._x_dataStack[0];
        const isAdd = arguments[0] === 'dash-add-backdrop';
        // Set the Alpine property directly — this is what saveAdd()/saveEdit() sends to the API.
        if (isAdd) { data.addYaml = arguments[1]; data.addYamlDirty = true; }
        else        { data.editYaml = arguments[1]; }
        // Also update the editor display so _cm_text() reflects the new content.
        const view = isAdd ? data._addEditor : data._editEditor;
        if (view) view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: arguments[1] } });
        """,
        backdrop_id,
        text,
    )


def _dialog_visible(driver) -> bool:
    """Return True when the in-DOM confirm dialog is currently shown."""
    return driver.execute_script(
        "const el = document.getElementById('cdialog-backdrop');"
        "return el ? el.classList.contains('cdialog-visible') : false;"
    )


def _open_add_dialog(driver, w):
    """Navigate to the dashboard and open the 'New card' dialog."""
    driver.get(_url("/budget/"))
    add_btn = w.until(EC.element_to_be_clickable(
        (By.XPATH, "//button[contains(text(),'New dashboard card')]")
    ))
    add_btn.click()
    w.until(EC.visibility_of_element_located((By.ID, "dash-add-backdrop")))
    time.sleep(1)  # wait for Alpine + CodeMirror to finish mounting inside the dialog


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDashboardCardsAPI:

    def test_01_presets_returns_list(self, driver, w, ctx):
        sess = _cards_session(driver)
        r = sess.get(PRESETS_URL)
        assert r.status_code == 200
        data = r.json()
        assert "presets" in data
        assert len(data["presets"]) > 0
        assert "name" in data["presets"][0]
        assert "yaml" in data["presets"][0]

    def test_02_create_cell_card(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\n"
            "title: Test Income\n"
            "query: \"type=income\"\n"
            "method: sum\n"
            "positioning:\n"
            "    position: 1\n"
            "    width: 2\n"
            "    height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        data = r.json()
        assert "card" in data
        card = data["card"]
        assert card["config"]["type"] == "cell"
        assert card["config"]["title"] == "Test Income"
        assert card["width"] == 2
        assert card["height"] == 1
        assert card["error"] is None
        ctx["card_id_cell"] = card["id"]

    def test_03_create_bar_chart_card(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        yaml_str = (
            "type: bar-chart\n"
            "group: tags\n"
            "title: Tags Chart\n"
            "positioning:\n"
            "    position: 2\n"
            "    width: 3\n"
            "    height: 3\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        data = r.json()
        card = data["card"]
        assert card["config"]["type"] == "bar-chart"
        assert card["width"] == 3
        assert card["height"] == 3
        ctx["card_id_bar"] = card["id"]

    def test_04_list_returns_cards_with_data(self, driver, w, ctx):
        sess = _cards_session(driver)
        r = sess.get(CARDS_URL)
        assert r.status_code == 200
        data = r.json()
        ids = [c["id"] for c in data["cards"]]
        assert ctx["card_id_cell"] in ids
        assert ctx["card_id_bar"] in ids
        # Cell card has a numeric value
        cell = next(c for c in data["cards"] if c["id"] == ctx["card_id_cell"])
        assert "value" in cell["data"]

    def test_05_invalid_yaml_returns_400(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, "type: not-a-real-type\n")
        assert r.status_code == 400
        assert "error" in r.json()

    def test_06_missing_group_returns_400(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, "type: bar-chart\ntitle: No group\n")
        assert r.status_code == 400

    def test_07_custom_python_cell(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\n"
            "title: Custom Python\n"
            "method: custom\n"
            "python: |\n"
            "    return 42\n"
            "positioning:\n"
            "    position: 5\n"
            "    width: 1\n"
            "    height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["data"]["value"] == 42.0
        ctx["card_id_custom"] = card["id"]

    def test_08_patch_card_yaml(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        new_yaml = (
            "type: cell\n"
            "title: Renamed Cell\n"
            "query: \"type=income\"\n"
            "method: sum\n"
            "positioning:\n"
            "    position: 1\n"
            "    width: 1\n"
            "    height: 1\n"
        )
        url = CARDS_URL.rstrip("/") + f"/{ctx['card_id_cell']}/"
        r = sess.patch(
            url,
            json={"yaml_config": new_yaml},
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
        card = r.json()["card"]
        assert card["config"]["title"] == "Renamed Cell"
        assert card["width"] == 1

    def test_09_resize_card(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        url = CARDS_URL.rstrip("/") + f"/{ctx['card_id_bar']}/resize/"
        r = sess.patch(
            url,
            json={"width": 4, "height": 2},
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["width"] == 4
        assert data["height"] == 2

    def test_10_reorder_cards(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        positions = [
            {"id": ctx["card_id_bar"],  "position": 1},
            {"id": ctx["card_id_cell"], "position": 2},
        ]
        r = sess.post(
            REORDER_URL,
            json={"positions": positions},
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        )
        assert r.status_code == 200

        # Verify order in list response
        cards = sess.get(CARDS_URL).json()["cards"]
        by_id = {c["id"]: c for c in cards}
        assert by_id[ctx["card_id_bar"]]["position"]  == 1
        assert by_id[ctx["card_id_cell"]]["position"] == 2

    def test_11_delete_custom_card(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        url = CARDS_URL.rstrip("/") + f"/{ctx['card_id_custom']}/"
        r = sess.delete(url, headers={"X-CSRFToken": csrf})
        assert r.status_code == 200
        cards = sess.get(CARDS_URL).json()["cards"]
        ids = [c["id"] for c in cards]
        assert ctx["card_id_custom"] not in ids

    def test_12_delete_404_for_wrong_user(self, driver, w, ctx):
        # Use a non-existent uid — should 404
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        url = CARDS_URL.rstrip("/") + "/9999999/"
        r = sess.delete(url, headers={"X-CSRFToken": csrf})
        assert r.status_code == 404

    def test_13_method_total_cell(self, driver, w, ctx):
        """method=total negates income and savings_wit types."""
        from conftest import api_delete, api_post, server_today

        today = server_today()
        # Create a regular expense (value=50) and an income expense (value=100)
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "TotalTest expense", "type": "expense",
            "value": "50.00", "date_due": today, "settled": False,
        })
        assert exp.status_code == 201
        inc = api_post("/api/v1/expenses/", ctx, json={
            "title": "TotalTest income", "type": "income",
            "value": "100.00", "date_due": today, "settled": False,
        })
        assert inc.status_code == 201
        ctx["_total_exp_ids"] = [exp.json()["id"], inc.json()["id"]]

        sess = _cards_session(driver)
        csrf = _csrf(sess)
        # method=sum should give 50 + 100 = 150
        r_sum = _post_card(sess, csrf, (
            "type: cell\ntitle: TotalTestSum\nmethod: sum\n"
            "positioning:\n  position: 90\n  width: 1\n  height: 1\n"
        ))
        assert r_sum.status_code == 201, r_sum.text
        # method=total should give 50 - 100 = -50
        r_tot = _post_card(sess, csrf, (
            "type: cell\ntitle: TotalTestTotal\nmethod: total\n"
            "positioning:\n  position: 91\n  width: 1\n  height: 1\n"
        ))
        assert r_tot.status_code == 201, r_tot.text
        ctx["_total_card_ids"] = [r_sum.json()["card"]["id"], r_tot.json()["card"]["id"]]

        cards = sess.get(CARDS_URL).json()["cards"]
        by_title = {c["config"]["title"]: c for c in cards}
        sum_val = by_title["TotalTestSum"]["data"]["value"]
        tot_val = by_title["TotalTestTotal"]["data"]["value"]
        assert sum_val >= 150.0, f"sum card expected ≥150, got {sum_val}"
        assert tot_val <= -50.0, f"total card expected ≤-50, got {tot_val}"

    def test_14_flip_signs(self, driver, w, ctx):
        """flip_signs: true multiplies computed value by -1."""
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, (
            "type: cell\ntitle: InvertTest\nmethod: total\nflip_signs: true\n"
            "positioning:\n  position: 92\n  width: 1\n  height: 1\n"
        ))
        assert r.status_code == 201, r.text
        val = r.json()["card"]["data"]["value"]
        # method=total with expenses from test_13 gives -50 minimum; inverted → +50
        assert val >= 50.0, f"inverted total card expected ≥50, got {val}"
        ctx["_invert_card_id"] = r.json()["card"]["id"]

    def test_15_chart_method_total(self, driver, w, ctx):
        """bar-chart with method=total returns negated values for income/savings_wit."""
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, (
            "type: bar-chart\ngroup: categories\ntitle: TotalChartTest\nmethod: total\n"
            "positioning:\n  position: 93\n  width: 3\n  height: 2\n"
        ))
        assert r.status_code == 201, r.text
        ctx["_total_chart_id"] = r.json()["card"]["id"]
        # Sum of all chart values must equal the method=total cell value (no query filter)
        cards = sess.get(CARDS_URL).json()["cards"]
        chart = next(c for c in cards if c["id"] == ctx["_total_chart_id"])
        chart_sum = sum(chart["data"]["values"])
        cell = next(c for c in cards if c["config"]["title"] == "TotalTestTotal")
        assert abs(chart_sum - cell["data"]["value"]) < 0.01, (
            f"chart total {chart_sum} should equal cell total {cell['data']['value']}"
        )

    def test_16_chart_invalid_method_returns_400(self, driver, w, ctx):
        """Charts only accept method=sum or method=total; count/custom return 400."""
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, (
            "type: bar-chart\ngroup: tags\ntitle: BadMethod\nmethod: count\n"
            "positioning:\n  position: 99\n  width: 2\n  height: 2\n"
        ))
        assert r.status_code == 400
        assert "error" in r.json()

    def test_17_cleanup_total_method_cards_and_expenses(self, driver, w, ctx):
        """Clean up expenses and cards created by tests 13–15."""
        from conftest import api_delete

        sess = _cards_session(driver)
        csrf = _csrf(sess)
        for card_id in ctx.get("_total_card_ids", []):
            sess.delete(CARDS_URL.rstrip("/") + f"/{card_id}/", headers={"X-CSRFToken": csrf})
        for cid in ["_invert_card_id", "_total_chart_id"]:
            if cid in ctx:
                sess.delete(CARDS_URL.rstrip("/") + f"/{ctx[cid]}/", headers={"X-CSRFToken": csrf})
        for exp_id in ctx.get("_total_exp_ids", []):
            api_delete(f"/api/v1/expenses/{exp_id}/", ctx)



class TestSandboxSecurity:
    """
    Pentest cases for the method=custom sandboxed Python execution.

    All tests POST a card (always 201 — AST/runtime errors surface in card["error"],
    not the HTTP status), delete it immediately, then assert on error/value.
    """

    # ── AST-level blocks ─────────────────────────────────────────────────────
    # These are caught before exec() is called.

    def test_sb_01_import_blocked(self, driver, w, ctx):
        card = _sandbox_post(driver, "import os\nreturn 0")
        assert card["error"] is not None
        assert "import" in card["error"].lower() or "not allowed" in card["error"].lower()

    def test_sb_02_from_import_blocked(self, driver, w, ctx):
        card = _sandbox_post(driver, "from os import getcwd\nreturn 0")
        assert card["error"] is not None
        assert "import" in card["error"].lower() or "not allowed" in card["error"].lower()

    def test_sb_03_dunder_attribute_blocked(self, driver, w, ctx):
        card = _sandbox_post(driver, "return (0).__class__")
        assert card["error"] is not None
        assert "dunder" in card["error"].lower() or "not allowed" in card["error"].lower()

    def test_sb_04_dunder_on_mro_blocked(self, driver, w, ctx):
        card = _sandbox_post(driver, "return str.__mro__[-1].__subclasses__()")
        assert card["error"] is not None
        assert "dunder" in card["error"].lower() or "not allowed" in card["error"].lower()

    def test_sb_05_dunder_globals_on_helper_blocked(self, driver, w, ctx):
        card = _sandbox_post(driver, "return query_sum.__globals__['os']")
        assert card["error"] is not None
        assert "dunder" in card["error"].lower() or "not allowed" in card["error"].lower()

    def test_sb_06_dunder_closure_on_helper_blocked(self, driver, w, ctx):
        card = _sandbox_post(driver, "return query_sum.__closure__[0].cell_contents")
        assert card["error"] is not None

    # ── Runtime NameError ────────────────────────────────────────────────────
    # AST passes (no Attribute dunder, no Import node), but the name is simply
    # absent from the sandbox namespace — fails at exec() time.

    def test_sb_07_dunder_import_name_unavailable(self, driver, w, ctx):
        # __import__ is a Name node (not Attribute) so AST check misses it,
        # but it is not in _SAFE_BUILTINS and __builtins__ is {}.
        card = _sandbox_post(driver, "return __import__('os').getcwd()")
        assert card["error"] is not None
        assert "runtime error" in card["error"].lower()

    def test_sb_08_getattr_unavailable(self, driver, w, ctx):
        card = _sandbox_post(driver, "return getattr(str, '__cl' + 'ass__')")
        assert card["error"] is not None
        assert "runtime error" in card["error"].lower()

    def test_sb_09_eval_unavailable(self, driver, w, ctx):
        card = _sandbox_post(driver, "return eval('__import__(\"os\").getcwd()')")
        assert card["error"] is not None
        assert "runtime error" in card["error"].lower()

    def test_sb_10_open_unavailable(self, driver, w, ctx):
        card = _sandbox_post(driver, "return len(open('/etc/passwd').read())")
        assert card["error"] is not None
        assert "runtime error" in card["error"].lower()

    def test_sb_11_globals_unavailable(self, driver, w, ctx):
        card = _sandbox_post(driver, "return len(globals())")
        assert card["error"] is not None
        assert "runtime error" in card["error"].lower()

    def test_sb_12_type_unavailable(self, driver, w, ctx):
        card = _sandbox_post(driver, "return type(query_sum)")
        assert card["error"] is not None
        assert "runtime error" in card["error"].lower()

    # ── __builtins__ leak check ───────────────────────────────────────────────
    # __builtins__ is accessible as a Name (not an Attribute, so AST passes),
    # but it must be the empty dict {} — not the real builtins module.

    def test_sb_13_builtins_is_empty_dict(self, driver, w, ctx):
        card = _sandbox_post(driver, "return len(__builtins__)")
        assert card["error"] is None, f"unexpected error: {card['error']}"
        assert card["data"]["value"] == 0.0

    # ── Type-safety and error handling ────────────────────────────────────────

    def test_sb_14_string_return_coerces_to_zero(self, driver, w, ctx):
        card = _sandbox_post(driver, "return 'not a number'")
        assert card["error"] is None
        assert card["data"]["value"] == 0.0

    def test_sb_15_none_return_coerces_to_zero(self, driver, w, ctx):
        card = _sandbox_post(driver, "return None")
        assert card["error"] is None
        assert card["data"]["value"] == 0.0

    def test_sb_16_runtime_exception_surfaces_as_error(self, driver, w, ctx):
        card = _sandbox_post(driver, "return 1 / 0")
        assert card["error"] is not None
        assert "runtime error" in card["error"].lower()

    def test_sb_17_swallowed_exception_returns_zero(self, driver, w, ctx):
        code = "try:\n  return 1 / 0\nexcept:\n  pass"
        card = _sandbox_post(driver, code)
        assert card["error"] is None
        assert card["data"]["value"] == 0.0

    # ── Data isolation ────────────────────────────────────────────────────────

    def test_sb_18_query_sum_empty_is_numeric(self, driver, w, ctx):
        # period_qs is already scoped to owning_feuser; must return a number, not crash
        card = _sandbox_post(driver, "return query_sum('')")
        assert card["error"] is None
        assert isinstance(card["data"]["value"], (int, float))

    def test_sb_19_sql_injection_in_query_sum_does_not_crash(self, driver, w, ctx):
        # Django ORM protects against raw SQL injection; the string is fed to the
        # query parser which treats unrecognised syntax as free text.
        card = _sandbox_post(driver, "return query_sum(\"' OR '1'='1\")")
        # Must not 500 — card was already asserted 201 in _sandbox_post.
        # Error in card["error"] is acceptable (parse error); a value is also fine.
        assert card.get("data") is not None or card.get("error") is not None


class TestDashboardBrowser:

    def test_20_dashboard_page_loads(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        time.sleep(3)
        assert driver.find_element(By.CSS_SELECTOR, ".dash-grid, .dash-loading")

    def test_21_grid_renders_cards(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        time.sleep(3)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".dash-card")) > 0

    def test_22_add_card_dialog_opens(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        time.sleep(3)
        driver.find_element(
            By.XPATH, "//button[contains(text(),'New dashboard card')]"
        ).click()
        time.sleep(1)
        assert driver.find_element(By.ID, "dash-add-backdrop").is_displayed()

    def test_23_preset_loads_into_editor(self, driver, w, ctx):
        # Dialog still open from previous test
        time.sleep(1)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        assert len(presets) > 0
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")

    def test_24_cancel_dialog(self, driver, w, ctx):
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)
        assert not driver.find_element(By.ID, "dash-add-backdrop").is_displayed()

    def test_25_edit_modal_opens_on_edit_button(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        time.sleep(3)
        first_card = driver.find_element(By.CSS_SELECTOR, ".dash-card")
        driver.execute_script("arguments[0].querySelector('.dash-card-edit-btn').click()", first_card)
        time.sleep(1)
        assert driver.find_element(By.ID, "dash-edit-backdrop").is_displayed()
        assert "type:" in _cm_text(driver, "dash-edit-backdrop")
        driver.find_element(
            By.XPATH, "//div[@id='dash-edit-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_27_sequential_presets_load_without_confirm(self, driver, w, ctx):
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        assert len(presets) >= 1
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        assert not _dialog_visible(driver), "Confirm dialog must not appear on back-to-back preset loads"
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_28_dirty_editor_confirm_cancel_keeps_content(self, driver, w, ctx):
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        assert len(presets) >= 1
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        driver.find_element(By.CSS_SELECTOR, "#dash-add-backdrop .cm-content").click()
        ActionChains(driver).send_keys("z").perform()
        dirty_text = _cm_text(driver, "dash-add-backdrop")
        assert dirty_text
        presets[0].click()
        time.sleep(1)
        assert _dialog_visible(driver), "Confirm dialog must appear when editor is dirty"
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert _cm_text(driver, "dash-add-backdrop") == dirty_text
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_29_dirty_editor_confirm_overwrite_loads_preset(self, driver, w, ctx):
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        assert len(presets) >= 1
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        driver.find_element(By.CSS_SELECTOR, "#dash-add-backdrop .cm-content").click()
        ActionChains(driver).send_keys("z").perform()
        presets[0].click()
        time.sleep(1)
        assert _dialog_visible(driver), "Confirm dialog must appear when editor is dirty"
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_30_empty_editor_loads_preset_without_confirm(self, driver, w, ctx):
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        assert len(presets) >= 1
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        # Clear the editor directly via CM dispatch (keeps _programmaticEdit=False so
        # onChange fires and sets addYamlDirty = False — same as user deleting all text)
        driver.execute_script("""
            const data = document.querySelector('[x-data="dashboardBoard"]')._x_dataStack[0];
            const view = data._addEditor;
            view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: '' } });
        """)
        time.sleep(1)
        assert _cm_text(driver, "dash-add-backdrop").strip() == ""
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        assert not _dialog_visible(driver), "Confirm dialog must not appear when editor was empty"
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_31_delete_card_via_browser_modal(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, (
            "type: cell\n"
            "title: BrowserDeleteTest\n"
            "method: sum\n"
            "positioning:\n"
            "    position: 99\n"
            "    width: 2\n"
            "    height: 1\n"
        ))
        assert r.status_code == 201, r.text

        driver.get(_url("/budget/"))
        time.sleep(3)
        driver.execute_script(
            "Array.from(document.querySelectorAll('.dash-card')).find("
            "  c => c.querySelector('.dash-card-title')?.textContent?.trim() === 'BrowserDeleteTest'"
            ")?.querySelector('.dash-card-edit-btn')?.click()"
        )
        time.sleep(1)
        assert driver.find_element(By.ID, "dash-edit-backdrop").is_displayed()
        driver.find_element(
            By.XPATH, "//div[@id='dash-edit-backdrop']//button[contains(@class,'btn-danger')]"
        ).click()
        time.sleep(1)
        assert _dialog_visible(driver)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert not driver.find_element(By.ID, "dash-edit-backdrop").is_displayed()
        titles = [el.text.strip() for el in driver.find_elements(By.CSS_SELECTOR, ".dash-card-title")]
        assert "BrowserDeleteTest" not in titles

    def test_32_cell_link_navigates(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, (
            "type: cell\n"
            "title: LinkTestCell\n"
            "query: type=income\n"
            "method: sum\n"
            "link: /budget/expenses/?search=type%3Dincome\n"
            "positioning:\n"
            "  position: 99\n"
            "  width: 2\n"
            "  height: 1\n"
        ))
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        driver.get(_url("/budget/"))
        time.sleep(3)
        driver.execute_script(
            "Array.from(document.querySelectorAll('.dash-card')).find("
            "  c => c.querySelector('.dash-card-title')?.textContent?.trim() === 'LinkTestCell'"
            ")?.querySelector('.dash-card-body--linked')?.click()"
        )
        time.sleep(2)
        assert "/budget/expenses/" in driver.current_url
        assert "type%3Dincome" in driver.current_url or "type=income" in driver.current_url

        sess.delete(CARDS_URL.rstrip("/") + f"/{card_id}/", headers={"X-CSRFToken": csrf})

    def test_34_cell_template_renders_in_card_body(self, driver, w, ctx):
        """Create a cell card with template: and verify the card body renders the template string."""
        yaml_str = (
            "type: cell\n"
            "title: TemplateUITest\n"
            "method: sum\n"
            "template: $VALUE $CURRENCY_SYMBOL incoming\n"
            "positioning:\n"
            "  position: 99\n"
            "  width: 2\n"
            "  height: 1\n"
        )
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        presets[0].click()
        time.sleep(1)
        _set_cm_text(driver, "dash-add-backdrop", yaml_str)
        time.sleep(1)
        assert "template" in _cm_text(driver, "dash-add-backdrop")
        driver.find_element(
            By.CSS_SELECTOR, "#dash-add-backdrop .dash-modal-actions .btn-primary"
        ).click()
        time.sleep(3)
        assert not driver.find_element(By.ID, "dash-add-backdrop").is_displayed()
        titles = [el.text.strip().lower() for el in driver.find_elements(By.CSS_SELECTOR, ".dash-card-title")]
        assert "TemplateUITest".lower() in titles
        bodies = driver.find_elements(By.CSS_SELECTOR, ".dash-card-body--cell .dash-cell-value")
        assert any("incoming" in (b.text or "") for b in bodies)
        driver.execute_script(
            "Array.from(document.querySelectorAll('.dash-card')).find("
            "  c => c.querySelector('.dash-card-title')?.textContent?.trim() === 'TemplateUITest'"
            ")?.querySelector('.dash-card-edit-btn')?.click()"
        )
        time.sleep(1)
        assert driver.find_element(By.ID, "dash-edit-backdrop").is_displayed()
        driver.find_element(
            By.XPATH, "//div[@id='dash-edit-backdrop']//button[contains(@class,'btn-danger')]"
        ).click()
        time.sleep(1)
        assert _dialog_visible(driver)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert not driver.find_element(By.ID, "dash-edit-backdrop").is_displayed()

    def test_26_cleanup_remaining_cards(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _csrf(sess)
        cards = sess.get(CARDS_URL).json()["cards"]
        for card in cards:
            url = CARDS_URL.rstrip("/") + f"/{card['id']}/"
            sess.delete(url, headers={"X-CSRFToken": csrf})
        assert sess.get(CARDS_URL).json()["cards"] == []
