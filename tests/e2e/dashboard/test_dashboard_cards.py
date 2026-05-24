"""
Dashboard cards: API CRUD, computed values, YAML validation,
color_breakpoints, flip_signs, method=total, presets, and browser smoke tests.
"""
import time

import requests
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, wait_text, click, api_post, api_delete, server_today,
    session_cookies, BASE_URL, setup_user, cleanup_user,
)

CARDS_URL   = BASE_URL + "/budget/dashboard/cards/"
REORDER_URL = BASE_URL + "/budget/dashboard/cards/reorder/"
PRESETS_URL = BASE_URL + "/budget/dashboard/cards/presets/"
RESET_URL   = BASE_URL + "/budget/dashboard/cards/reset/"


def _cards_session(driver) -> requests.Session:
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


def _csrf(sess) -> str:
    return next((c.value for c in sess.cookies if c.name == "csrftoken"), "")


def _post_card(sess, csrf, yaml_str) -> requests.Response:
    return sess.post(CARDS_URL, json={"yaml_config": yaml_str},
                     headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})


def _delete_card(sess, csrf, card_id):
    sess.delete(f"{CARDS_URL}{card_id}/", headers={"X-CSRFToken": csrf})


def _cm_text(driver, backdrop_id: str) -> str:
    return driver.execute_script(
        "const el = document.querySelector('#' + arguments[0] + ' .cm-content');"
        "return el ? el.textContent : '';",
        backdrop_id,
    )


def _set_cm_text(driver, backdrop_id: str, text: str):
    driver.execute_script(
        """
        const data = document.querySelector('[x-data="dashboardBoard"]')._x_dataStack[0];
        const isAdd = arguments[0] === 'dash-add-backdrop';
        if (isAdd) { data.addYaml = arguments[1]; data.addYamlDirty = true; }
        else        { data.editYaml = arguments[1]; }
        const view = isAdd ? data._addEditor : data._editEditor;
        if (view) view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: arguments[1] } });
        """,
        backdrop_id,
        text,
    )


def _dialog_visible(driver) -> bool:
    return driver.execute_script(
        "const el = document.getElementById('cdialog-backdrop');"
        "return el ? el.classList.contains('cdialog-visible') : false;"
    )


def _open_add_dialog(driver, w):
    driver.get(_url("/budget/"))
    time.sleep(3)
    driver.find_element(By.XPATH, "//button[contains(text(),'New dashboard card')]").click()
    time.sleep(1)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def sess(driver, ctx):
    """requests.Session carrying the browser session cookie."""
    driver.get(_url("/budget/"))
    s = _cards_session(driver)
    return s


class TestCardCrud:

    def test_create_cell(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\ntitle: Test Cell\nmethod: sum\n"
            "positioning:\n  position: 1\n  width: 2\n  height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["config"]["title"] == "Test Cell"
        ctx["cell_id"] = card["id"]

    def test_get_cell(self, driver, w, ctx, sess):
        r = sess.get(CARDS_URL)
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["cards"]]
        assert ctx["cell_id"] in ids

    def test_update_cell(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        new_yaml = (
            "type: cell\ntitle: Updated Cell\nmethod: count\n"
            "positioning:\n  position: 1\n  width: 2\n  height: 1\n"
        )
        r = sess.patch(f"{CARDS_URL}{ctx['cell_id']}/",
                       json={"yaml_config": new_yaml},
                       headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.json()["card"]["config"]["title"] == "Updated Cell"

    def test_create_bar_chart(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: bar-chart\ntitle: Bar Chart\nmethod: sum\ngroup: categories\n"
            "positioning:\n  position: 2\n  width: 4\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        ctx["bar_id"] = r.json()["card"]["id"]

    def test_delete_cards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        for key in ("cell_id", "bar_id"):
            if key in ctx:
                _delete_card(sess, csrf, ctx.pop(key))

    def test_yaml_validation_error(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, "type: not_a_valid_type\ntitle: Bad\n")
        assert r.status_code == 400

    def test_custom_method_rejected_for_all_types(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        cell_yaml = (
            "type: cell\ntitle: Bad Cell\nmethod: custom\n"
            "positioning:\n  position: 3\n  width: 2\n  height: 1\n"
        )
        assert _post_card(sess, csrf, cell_yaml).status_code == 400
        chart_yaml = (
            "type: bar-chart\ntitle: Bad Chart\nmethod: custom\ngroup: categories\n"
            "positioning:\n  position: 3\n  width: 4\n  height: 2\n"
        )
        assert _post_card(sess, csrf, chart_yaml).status_code == 400

    def test_missing_group_returns_400(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, "type: bar-chart\ntitle: No group\n")
        assert r.status_code == 400

    def test_mobile_resize(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = ("type: cell\ntitle: MobileResizeCard\nmethod: sum\n"
                    "positioning:\n  position: 1\n  width: 4\n  height: 2\n")
        card_id = _post_card(sess, csrf, yaml_str).json()["card"]["id"]
        r = sess.patch(f"{CARDS_URL}{card_id}/resize/",
                       json={"width": 3, "height": 2, "mobile": True},
                       headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.json()["mobile_width"] == 3
        assert r.json()["mobile_height"] == 2
        _delete_card(sess, csrf, card_id)

    def test_mobile_resize_clamps_to_6_cols(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = ("type: cell\ntitle: ClampCard\nmethod: sum\n"
                    "positioning:\n  position: 1\n  width: 4\n  height: 1\n")
        card_id = _post_card(sess, csrf, yaml_str).json()["card"]["id"]
        r = sess.patch(f"{CARDS_URL}{card_id}/resize/",
                       json={"width": 12, "height": 1, "mobile": True},
                       headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.json()["mobile_width"] == 6
        _delete_card(sess, csrf, card_id)

    def test_mobile_reorder(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml1 = ("type: cell\ntitle: MobOrdA\nmethod: sum\n"
                 "positioning:\n  position: 1\n  width: 2\n  height: 1\n")
        yaml2 = ("type: cell\ntitle: MobOrdB\nmethod: sum\n"
                 "positioning:\n  position: 2\n  width: 2\n  height: 1\n")
        id1 = _post_card(sess, csrf, yaml1).json()["card"]["id"]
        id2 = _post_card(sess, csrf, yaml2).json()["card"]["id"]
        positions = [{"id": id1, "position": 2}, {"id": id2, "position": 1}]
        r = sess.post(REORDER_URL, json={"positions": positions, "mobile": True},
                      headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
        assert r.status_code == 200
        cards = sess.get(CARDS_URL).json()["cards"]
        by_id = {c["id"]: c for c in cards}
        assert by_id[id2]["mobile_position"] == 1
        assert by_id[id1]["mobile_position"] == 2
        _delete_card(sess, csrf, id1)
        _delete_card(sess, csrf, id2)

    def test_mobile_positioning_yaml_roundtrip(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\ntitle: MobilePositionTest\nmethod: sum\n"
            "positioning:\n  position: 1\n  width: 4\n  height: 2\n"
            "  mobile:\n    position: 3\n    width: 6\n    height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        card = r.json()["card"]
        assert card["width"] == 4
        assert card["height"] == 2
        assert card["mobile_position"] == 3
        assert card["mobile_width"] == 6
        assert card["mobile_height"] == 1
        _delete_card(sess, csrf, card["id"])

    def test_delete_404_wrong_user(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = sess.delete(f"{CARDS_URL}9999999/", headers={"X-CSRFToken": csrf})
        assert r.status_code == 404

    def test_chart_rejects_count_method(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: bar-chart\ntitle: CountChart\nmethod: count\ngroup: categories\n"
            "positioning:\n  position: 3\n  width: 4\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400

    def test_chart_method_total(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        inc = api_post("/api/v1/expenses/", ctx, json={
            "title": "ChartTotal Inc", "type": "income", "value": "100.00",
            "date_due": today, "settled": True,
        })
        assert inc.status_code == 201
        csrf = _csrf(sess)
        yaml_str = (
            "type: bar-chart\ntitle: TotalBarChart\nmethod: total\ngroup: categories\n"
            "positioning:\n  position: 93\n  width: 3\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]
        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        chart = next((c for c in cards if c["id"] == card_id), None)
        assert chart is not None
        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{inc.json()['id']}/", ctx)


class TestCardData:

    def test_computed_sum(self, driver, w, ctx, sess):
        """Create an expense and verify the cell computes the correct sum."""
        today = server_today()
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "Card Compute", "type": "expense", "value": "123.45",
            "date_due": today, "settled": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        year, month = today[:4], today[5:7]

        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\ntitle: SumCell\nmethod: sum\n"
            "query: \"type=expense settled=yes\"\n"
            "positioning:\n  position: 10\n  width: 2\n  height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        data_r = sess.get(CARDS_URL, params={"year": year, "month": month})
        cards = data_r.json()["cards"]
        card_data = next((c["data"] for c in cards if c["id"] == card_id), None)
        assert card_data is not None
        assert float(card_data.get("value", 0)) >= 123.45

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_method_total(self, driver, w, ctx, sess):
        """method=total: income entries count as negative."""
        today = server_today()
        year, month = today[:4], today[5:7]
        inc_r = api_post("/api/v1/expenses/", ctx, json={
            "title": "Total Inc", "type": "income", "value": "100.00",
            "date_due": today, "settled": True,
        })
        assert inc_r.status_code == 201
        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\ntitle: TotalCell\nmethod: total\n"
            "positioning:\n  position: 11\n  width: 2\n  height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]
        data_r = sess.get(CARDS_URL, params={"year": year, "month": month})
        card_data = next((c["data"] for c in data_r.json()["cards"] if c["id"] == card_id), {})
        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{inc_r.json()['id']}/", ctx)
        # income should reduce the total value
        assert float(card_data.get("value", 0)) <= 0

    def test_flip_signs(self, driver, w, ctx, sess):
        """flip_signs: true inverts the computed value."""
        today = server_today()
        year, month = today[:4], today[5:7]
        exp_r = api_post("/api/v1/expenses/", ctx, json={
            "title": "FlipSign Exp", "type": "expense", "value": "50.00",
            "date_due": today, "settled": True,
        })
        assert exp_r.status_code == 201
        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\ntitle: FlipCell\nmethod: sum\nflip_signs: true\n"
            "query: \"type=expense\"\n"
            "positioning:\n  position: 12\n  width: 2\n  height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]
        data_r = sess.get(CARDS_URL, params={"year": year, "month": month})
        card_data = next((c["data"] for c in data_r.json()["cards"] if c["id"] == card_id), {})
        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{exp_r.json()['id']}/", ctx)
        # With flip_signs, expense sum (positive) becomes negative
        assert float(card_data.get("value", 0)) < 0


class TestColorBreakpoints:

    def test_breakpoints_stored(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\ntitle: BPCell\nmethod: sum\n"
            "color: green\n"
            "color_breakpoints:\n"
            "  - less_than: 100\n    color: yellow\n"
            "  - less_than: 10\n    color: red\n"
            "positioning:\n  position: 20\n  width: 2\n  height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        config = r.json()["card"]["config"]
        assert len(config["color_breakpoints"]) == 2
        _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_non_numeric_breakpoint_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\ntitle: BadBP\nmethod: sum\n"
            "color_breakpoints:\n"
            "  - less_than: notanumber\n    color: red\n"
            "positioning:\n  position: 21\n  width: 2\n  height: 1\n"
        )
        assert _post_card(sess, csrf, yaml_str).status_code == 400


class TestReorderAndResize:

    def test_reorder(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml1 = ("type: cell\ntitle: CardA\nmethod: sum\n"
                 "positioning:\n  position: 1\n  width: 2\n  height: 1\n")
        yaml2 = ("type: cell\ntitle: CardB\nmethod: sum\n"
                 "positioning:\n  position: 2\n  width: 2\n  height: 1\n")
        id1 = _post_card(sess, csrf, yaml1).json()["card"]["id"]
        id2 = _post_card(sess, csrf, yaml2).json()["card"]["id"]
        r = sess.post(REORDER_URL, json={"order": [id2, id1]},
                      headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
        assert r.status_code == 200
        _delete_card(sess, csrf, id1)
        _delete_card(sess, csrf, id2)

    def test_resize(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = ("type: cell\ntitle: ResizeCard\nmethod: sum\n"
                    "positioning:\n  position: 1\n  width: 2\n  height: 1\n")
        card_id = _post_card(sess, csrf, yaml_str).json()["card"]["id"]
        r = sess.patch(f"{CARDS_URL}{card_id}/resize/",
                       json={"width": 4, "height": 2},
                       headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
        assert r.status_code == 200
        _delete_card(sess, csrf, card_id)


class TestPresets:

    def test_presets_endpoint(self, driver, w, ctx, sess):
        r = sess.get(PRESETS_URL)
        assert r.status_code == 200
        assert len(r.json()["presets"]) > 0


class TestBrowserSmoke:

    def test_dashboard_loads(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        wait_text(driver, w, "Dashboard")

    def test_grid_renders_cards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = ("type: cell\ntitle: GridTestCard\nmethod: sum\n"
                    "positioning:\n  position: 1\n  width: 2\n  height: 1\n")
        card_id = _post_card(sess, csrf, yaml_str).json()["card"]["id"]
        driver.get(_url("/budget/"))
        time.sleep(3)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".dash-card")) > 0
        _delete_card(sess, csrf, card_id)

    def test_add_card_dialog(self, driver, w, ctx):
        _open_add_dialog(driver, w)
        assert driver.find_element(By.ID, "dash-add-backdrop").is_displayed()
        assert "yaml" in driver.page_source.lower()

    def test_preset_loads_into_editor(self, driver, w, ctx):
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        assert len(presets) > 0
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")

    def test_cancel_dialog(self, driver, w, ctx):
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)
        assert not driver.find_element(By.ID, "dash-add-backdrop").is_displayed()

    def test_edit_modal_opens(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = ("type: cell\ntitle: EditModalCard\nmethod: sum\n"
                    "positioning:\n  position: 1\n  width: 2\n  height: 1\n")
        card_id = _post_card(sess, csrf, yaml_str).json()["card"]["id"]
        driver.get(_url("/budget/"))
        time.sleep(3)
        driver.execute_script(
            "Array.from(document.querySelectorAll('.dash-card')).find("
            "  c => c.querySelector('.dash-card-title')?.textContent?.trim() === 'EditModalCard'"
            ")?.querySelector('.dash-card-edit-btn')?.click()"
        )
        time.sleep(1)
        assert driver.find_element(By.ID, "dash-edit-backdrop").is_displayed()
        assert "type:" in _cm_text(driver, "dash-edit-backdrop")
        driver.find_element(
            By.XPATH, "//div[@id='dash-edit-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)
        _delete_card(sess, csrf, card_id)

    def test_sequential_presets_no_confirm(self, driver, w, ctx):
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        assert len(presets) >= 1
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        presets[0].click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        assert not _dialog_visible(driver)
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_dirty_editor_confirm_cancel_keeps_content(self, driver, w, ctx):
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        presets[0].click()
        time.sleep(1)
        driver.execute_script("""
            const data = document.querySelector('[x-data="dashboardBoard"]')._x_dataStack[0];
            const view = data._addEditor;
            if (view) {
                const len = view.state.doc.length;
                view.dispatch({ changes: { from: len, to: len, insert: 'z' } });
            }
        """)
        time.sleep(0.3)
        dirty_text = _cm_text(driver, "dash-add-backdrop")
        presets[0].click()
        time.sleep(1)
        assert _dialog_visible(driver)
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert _cm_text(driver, "dash-add-backdrop") == dirty_text
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_dirty_editor_confirm_overwrite_loads_preset(self, driver, w, ctx):
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        presets[0].click()
        time.sleep(1)
        driver.execute_script("""
            const data = document.querySelector('[x-data="dashboardBoard"]')._x_dataStack[0];
            const view = data._addEditor;
            if (view) {
                const len = view.state.doc.length;
                view.dispatch({ changes: { from: len, to: len, insert: 'z' } });
            }
        """)
        time.sleep(0.3)
        presets[0].click()
        time.sleep(1)
        assert _dialog_visible(driver)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "type:" in _cm_text(driver, "dash-add-backdrop")
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_empty_editor_loads_preset_without_confirm(self, driver, w, ctx):
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        presets[0].click()
        time.sleep(1)
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
        assert not _dialog_visible(driver)
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_delete_card_via_browser_modal(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, (
            "type: cell\ntitle: BrowserDeleteTest\nmethod: sum\n"
            "positioning:\n  position: 99\n  width: 2\n  height: 1\n"
        ))
        assert r.status_code == 201
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

    def test_cell_link_navigates(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, (
            "type: cell\ntitle: LinkTestCell\nquery: type=income\nmethod: sum\n"
            "link: /budget/expenses/?search=type%3Dincome\n"
            "positioning:\n  position: 99\n  width: 2\n  height: 1\n"
        ))
        assert r.status_code == 201
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
        _delete_card(sess, csrf, card_id)

    def test_cell_template_renders(self, driver, w, ctx, sess):
        yaml_str = (
            "type: cell\ntitle: TemplateUITest\nmethod: sum\n"
            "template: $VALUE $CURRENCY_SYMBOL incoming\n"
            "positioning:\n  position: 99\n  width: 2\n  height: 1\n"
        )
        _open_add_dialog(driver, w)
        presets = driver.find_elements(By.CSS_SELECTOR, ".dash-presets .btn")
        presets[0].click()
        time.sleep(1)
        _set_cm_text(driver, "dash-add-backdrop", yaml_str)
        time.sleep(1)
        driver.find_element(
            By.CSS_SELECTOR, "#dash-add-backdrop .dash-modal-actions .btn-primary"
        ).click()
        time.sleep(3)
        titles = [el.text.strip().lower() for el in driver.find_elements(By.CSS_SELECTOR, ".dash-card-title")]
        assert "templateuitest" in titles
        bodies = driver.find_elements(By.CSS_SELECTOR, ".dash-card-body--cell .dash-cell-value")
        assert any("incoming" in (b.text or "") for b in bodies)
        # Cleanup via edit modal delete
        driver.execute_script(
            "Array.from(document.querySelectorAll('.dash-card')).find("
            "  c => c.querySelector('.dash-card-title')?.textContent?.trim() === 'TemplateUITest'"
            ")?.querySelector('.dash-card-edit-btn')?.click()"
        )
        time.sleep(1)
        driver.find_element(
            By.XPATH, "//div[@id='dash-edit-backdrop']//button[contains(@class,'btn-danger')]"
        ).click()
        time.sleep(1)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)

    _BP_YAML = (
        "type: cell\n"
        "title: '{title}'\n"
        "method: sum\n"
        "query: '{tag}'\n"
        "color: '#1a3326'\n"
        "color_lightmode: '#a7f3d0'\n"
        "color_breakpoints:\n"
        "  - less_than: 100\n"
        "    color: '#3b2e00'\n"
        "    color_lightmode: '#fef08a'\n"
        "  - less_than: 10\n"
        "    color: '#3b0a0a'\n"
        "    color_lightmode: '#fecaca'\n"
        "positioning:\n"
        "  position: 99\n"
        "  width: 2\n"
        "  height: 1\n"
    )

    _BP_COLORS = {
        True:  {"green": "#1a3326", "yellow": "#3b2e00", "red": "#3b0a0a"},
        False: {"green": "#a7f3d0", "yellow": "#fef08a", "red": "#fecaca"},
    }

    def _bp_is_dark(self, driver):
        return driver.execute_script(
            "return window.matchMedia('(prefers-color-scheme: dark)').matches;"
        )

    def _bp_card_style(self, driver, title):
        return driver.execute_script(
            "const card = Array.from(document.querySelectorAll('.dash-card')).find("
            "  c => c.querySelector('.dash-card-title')?.textContent?.trim() === arguments[0]"
            ");"
            "return card ? (card.getAttribute('style') || '') : '';",
            title,
        )

    def _bp_setup(self, driver, ctx, sess, tag, value, title):
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": f"BPBrowserTest {tag}", "type": "income",
            "value": str(value), "date_due": server_today(), "settled": False,
        })
        assert exp.status_code == 201
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, self._BP_YAML.format(title=title, tag=tag))
        assert r.status_code == 201
        return exp.json()["id"], r.json()["card"]["id"]

    def _bp_teardown(self, driver, ctx, sess, exp_id, card_id):
        csrf = _csrf(sess)
        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{exp_id}/", ctx)

    def test_color_breakpoint_green(self, driver, w, ctx, sess):
        exp_id, card_id = self._bp_setup(driver, ctx, sess, "bptest_35a", 200, "BPGreenCard")
        try:
            driver.get(_url("/budget/"))
            time.sleep(3)
            dark = self._bp_is_dark(driver)
            expected = self._BP_COLORS[dark]["green"]
            style = self._bp_card_style(driver, "BPGreenCard")
            assert style, "Card not found or has no style"
            assert expected in style, f"Expected green ({expected}) in style: {style}"
        finally:
            self._bp_teardown(driver, ctx, sess, exp_id, card_id)

    def test_color_breakpoint_yellow(self, driver, w, ctx, sess):
        exp_id, card_id = self._bp_setup(driver, ctx, sess, "bptest_35b", 50, "BPYellowCard")
        try:
            driver.get(_url("/budget/"))
            time.sleep(3)
            dark = self._bp_is_dark(driver)
            expected = self._BP_COLORS[dark]["yellow"]
            style = self._bp_card_style(driver, "BPYellowCard")
            assert style, "Card not found or has no style"
            assert expected in style, f"Expected yellow ({expected}) in style: {style}"
        finally:
            self._bp_teardown(driver, ctx, sess, exp_id, card_id)

    def test_color_breakpoint_red(self, driver, w, ctx, sess):
        exp_id, card_id = self._bp_setup(driver, ctx, sess, "bptest_35c", 5, "BPRedCard")
        try:
            driver.get(_url("/budget/"))
            time.sleep(3)
            dark = self._bp_is_dark(driver)
            expected = self._BP_COLORS[dark]["red"]
            style = self._bp_card_style(driver, "BPRedCard")
            assert style, "Card not found or has no style"
            assert expected in style, f"Expected red ({expected}) in style: {style}"
        finally:
            self._bp_teardown(driver, ctx, sess, exp_id, card_id)

    def test_reset_dashboard_api(self, driver, w, ctx, sess):
        """Reset API replaces all cards with the 7 default cards."""
        csrf = _csrf(sess)
        # Delete all existing cards first
        for card in sess.get(CARDS_URL).json()["cards"]:
            _delete_card(sess, csrf, card["id"])
        assert sess.get(CARDS_URL).json()["cards"] == []
        # Hit the reset endpoint
        r = sess.post(RESET_URL, json={}, headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
        assert r.status_code == 200
        cards = r.json()["cards"]
        assert len(cards) == 10
        titles = [c["config"]["title"] for c in cards]
        assert "Income" in titles
        assert "Left to spend" in titles

    def test_reset_dashboard_browser(self, driver, w, ctx, sess):
        """Reset button in browser shows confirmation dialog and reloads default cards."""
        csrf = _csrf(sess)
        # Add a marker card so we can verify it disappears
        r = _post_card(sess, csrf, (
            "type: cell\ntitle: ResetMarker\nmethod: sum\n"
            "positioning:\n  position: 99\n  width: 2\n  height: 1\n"
        ))
        assert r.status_code == 201
        driver.get(_url("/budget/"))
        time.sleep(3)

        def _titles():
            return driver.execute_script(
                "return Array.from(document.querySelectorAll('.dash-card-title'))"
                ".map(el => el.textContent.trim().toLowerCase())"
                ".filter(t => t !== '');"
            )

        # Marker card should be visible
        assert "resetmarker" in _titles()
        # Click "Reset dashboard"
        driver.find_element(
            By.XPATH, "//*[@id='dash-reset-btn']"
        ).click()
        time.sleep(1)
        assert _dialog_visible(driver)
        # Cancel: marker should still be there
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert not _dialog_visible(driver)
        assert "resetmarker" in _titles()
        # Confirm reset
        driver.find_element(
            By.XPATH, "//*[@id='dash-reset-btn']"
        ).click()
        time.sleep(1)
        assert _dialog_visible(driver)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(3)
        titles = _titles()
        assert "resetmarker" not in titles
        assert "income" in titles

    def test_cleanup_all_cards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        cards = sess.get(CARDS_URL).json()["cards"]
        for card in cards:
            _delete_card(sess, csrf, card["id"])
        assert sess.get(CARDS_URL).json()["cards"] == []


class TestUnknownKeys:
    """Unknown YAML keys are rejected for all card types and nested structures."""

    def test_unknown_top_level_key_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: line-chart\ntitle: T\nmethod: cum\n"
            "suggsted_max: 1000\n"
            "series:\n  - label: X\n"
            "positioning:\n  position: 0\n  width: 4\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400

    def test_unknown_series_key_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: line-chart\ntitle: T\nmethod: cum\n"
            "series:\n  - label: X\n    colur: '#ff0000'\n"
            "positioning:\n  position: 0\n  width: 4\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400

    def test_unknown_positioning_key_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: line-chart\ntitle: T\nmethod: cum\n"
            "series:\n  - label: X\n"
            "positioning:\n  position: 0\n  width: 4\n  height: 2\n  typo_key: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400

    def test_unknown_cell_key_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: cell\ntitle: T\nmethod: sum\n"
            "colour: '#ff0000'\n"
            "positioning:\n  position: 0\n  width: 2\n  height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400


class TestSpacerCard:

    def test_create_spacer_minimal(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf,
            "type: spacer\npositioning:\n  position: 99\n  width: 2\n  height: 1\n")
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["config"]["type"] == "spacer"
        assert card["config"]["hide_on"] == ""
        _delete_card(sess, csrf, card["id"])

    def test_spacer_hide_on_mobile(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf,
            "type: spacer\nhide_on: mobile\npositioning:\n  position: 99\n  width: 2\n  height: 1\n")
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["config"]["hide_on"] == "mobile"
        _delete_card(sess, csrf, card["id"])

    def test_spacer_hide_on_desktop(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf,
            "type: spacer\nhide_on: desktop\npositioning:\n  position: 99\n  width: 2\n  height: 1\n")
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["config"]["hide_on"] == "desktop"
        _delete_card(sess, csrf, card["id"])

    def test_spacer_invalid_hide_on_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf,
            "type: spacer\nhide_on: tablet\npositioning:\n  position: 99\n  width: 2\n  height: 1\n")
        assert r.status_code == 400

    def test_spacer_rejects_unknown_keys(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf,
            "type: spacer\ntitle: Oops\npositioning:\n  position: 99\n  width: 2\n  height: 1\n")
        assert r.status_code == 400

    def test_spacer_data_is_empty(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf,
            "type: spacer\npositioning:\n  position: 99\n  width: 2\n  height: 1\n")
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["data"] == {}
        _delete_card(sess, csrf, card["id"])
