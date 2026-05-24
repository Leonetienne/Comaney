"""
Express Creation confirm path: comprehensive browser-driven tests.

ALL interaction with the app goes through the browser UI.
Shell / API are used exclusively for reading state (verification).

All tests require a working AI (trial key or user key) and are skipped when
the AI is unavailable.

Setup (UI only):
  - Create user via setup_user
  - Create project "Schanzenfest 2026" via /projects/ form
  - Upload projectpic.jpg via project detail page
  - Add offline members "Volker Sauerbier" and "Andreas Krawall" via project detail form

Cases covered:
  1. Keep None tab -> expense saved without project
  2. Select Project tab -> expense saved with project "Schanzenfest 2026"
  3. Keep None tab (explicit, after AI suggested project) -> no project
  4. Direct Buddy: me pays, Volker gets 35%
  5. Direct Buddy: Volker pays, me gets 40%
  6. Project: Volker pays, Andreas deselected, me gets 55%
  7. Project: me pays, Andreas deselected, Volker gets 45%
"""
import os
import re
import subprocess
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, api_get, setup_user, cleanup_user

DOCKER_WEB = "comaney-web-1"
ASSET = os.path.join(os.path.dirname(__file__), "assets", "projectpic.jpg")
AI_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Shell helpers (verification only)
# ---------------------------------------------------------------------------

def _shell(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, f"Shell failed:\n{r.stderr}"
    return r.stdout.strip()


def _get_pk(email: str) -> int:
    return int(_shell(
        f"from feusers.models import FeUser; "
        f"print(FeUser.objects.get(email='{email}').pk)"
    ))


def _get_dummy_pk(project_uid: int, name: str) -> int:
    return int(_shell(
        f"from buddies.models import DummyUser, Project; "
        f"p = Project.objects.get(pk={project_uid}); "
        f"print(DummyUser.objects.get(owning_group=p, display_name='{name}').pk)"
    ))


def _expense_project_name(title: str, owner_email: str) -> str | None:
    result = _shell(
        f"from budget.models import Expense; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"e = Expense.objects.filter(title__startswith='{title}', owning_feuser=u).first(); "
        f"print(e.project.name if e and e.project_id else 'None')"
    )
    return None if result == "None" else result


def _expense_spendings(title: str, owner_email: str) -> list[dict]:
    import json as _json
    result = _shell(
        f"import json; from budget.models import Expense; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"e = Expense.objects.filter(title__startswith='{title}', owning_feuser=u).first(); "
        f"rows = [dict(type='feuser' if bs.participant_feuser_id else 'dummy', "
        f"id=bs.participant_feuser_id or bs.participant_dummy_id, "
        f"share=float(bs.share_percent)) "
        f"for bs in (e.buddy_spendings.all() if e else [])]; "
        f"print(json.dumps(rows))"
    )
    return _json.loads(result)


def _expense_in_api(title_prefix: str, ctx: dict) -> bool:
    expenses = api_get("/api/v1/expenses/", ctx, params={"q": title_prefix}).json().get("expenses", [])
    return any(e["title"].startswith(title_prefix) for e in expenses)


# ---------------------------------------------------------------------------
# UI helpers (setup and interaction)
# ---------------------------------------------------------------------------

def _ui_create_project(driver, name: str, description: str = "") -> int:
    """Create a project via /projects/ and return its uid (from redirect URL)."""
    driver.get(_url("/projects/"))
    time.sleep(1)
    driver.execute_script(
        "arguments[0].value = arguments[1];",
        driver.find_element(By.ID, "project-name"), name,
    )
    if description:
        driver.execute_script(
            "arguments[0].value = arguments[1];",
            driver.find_element(By.ID, "project-description"), description,
        )
    driver.find_element(By.ID, "btn-create-project").click()
    time.sleep(2)
    m = re.search(r"/projects/(\d+)/", driver.current_url)
    assert m, f"Expected redirect to /projects/<uid>/, got: {driver.current_url}"
    return int(m.group(1))


def _ui_upload_picture(driver, project_uid: int) -> None:
    """Upload projectpic.jpg via the project settings page."""
    driver.get(_url(f"/projects/{project_uid}/settings/"))
    time.sleep(1)
    driver.execute_script("document.getElementById('project-pic-input').style.display = 'block';")
    driver.find_element(By.ID, "project-pic-input").send_keys(ASSET)
    time.sleep(0.3)
    # Fallback submit in case the change-event auto-upload did not fire
    driver.execute_script(
        "var f = document.getElementById('project-pic-upload-form'); if (f) f.submit();"
    )
    time.sleep(2)


def _get_personal_dummy_pk(email: str, name: str) -> int:
    return int(_shell(
        f"from buddies.models import DummyUser; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"print(DummyUser.objects.get(owning_feuser=u, display_name='{name}').pk)"
    ))


def _ui_add_personal_dummy(driver, name: str) -> None:
    """Add a personal offline buddy via the /buddies/ page form."""
    driver.get(_url("/buddies/"))
    time.sleep(1)
    inp = driver.find_element(By.CSS_SELECTOR, "form.inline-form input[name='display_name']")
    driver.execute_script("arguments[0].value = arguments[1];", inp, name)
    driver.execute_script("arguments[0].closest('form').submit();", inp)
    time.sleep(2)
    assert name in driver.page_source, \
        f"'{name}' must appear on the buddies page after adding as personal offline buddy"


def _ui_add_dummy(driver, project_uid: int, name: str) -> None:
    """Add an offline member via the project settings form."""
    driver.get(_url(f"/projects/{project_uid}/settings/"))
    time.sleep(2)
    inp = driver.find_element(By.CSS_SELECTOR, "input[name='display_name']")
    driver.execute_script("arguments[0].value = arguments[1];", inp, name)
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
        "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
        inp,
    )
    driver.execute_script(
        "document.getElementById('btn-group-add-dummy').closest('form').submit();"
    )
    time.sleep(2)
    assert name in driver.page_source, \
        f"'{name}' must appear on the project page after adding as offline member"


def _ui_parse(driver, description: str) -> bool:
    """Navigate to express creation, submit description, wait for preview cards.

    Returns True when cards appear, False if AI is unavailable or timed out.
    """
    driver.get(_url("/budget/ai/express-creation/"))
    time.sleep(1)
    if "/profile" in driver.current_url:
        return False
    src = driver.page_source
    if "temporarily unavailable" in src or "Monthly AI limit reached" in src:
        return False
    driver.execute_script(
        "arguments[0].value = arguments[1];",
        driver.find_element(By.CSS_SELECTOR, "textarea[name=description]"), description,
    )
    driver.find_element(By.ID, "parse-btn").click()
    deadline = time.time() + AI_TIMEOUT
    while time.time() < deadline:
        if driver.find_elements(By.CSS_SELECTOR, ".preview-card"):
            return True
        time.sleep(3)
    return False


def _first_card(driver):
    return driver.find_elements(By.CSS_SELECTOR, ".preview-card")[0]


def _card_title(card) -> str:
    """Read the AI-generated title from the card's title field."""
    return card.find_element(By.CSS_SELECTOR, ".edit-title").get_property("value").strip()


def _set_value(driver, card, amount: str) -> None:
    inp = card.find_element(By.CSS_SELECTOR, ".edit-value")
    driver.execute_script("arguments[0].value = arguments[1];", inp, amount)
    driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", inp)
    time.sleep(0.2)


def _click_tab(driver, card, tab_class: str) -> None:
    el = card.find_element(By.CSS_SELECTOR, tab_class)
    driver.execute_script("arguments[0].click();", el)
    time.sleep(0.5)


def _set_payer(driver, card, option_text_fragment: str) -> None:
    sel = card.find_element(By.CSS_SELECTOR, ".buddy-upfront-select")
    options = sel.find_elements(By.TAG_NAME, "option")
    target = next(o for o in options if option_text_fragment in o.text)
    driver.execute_script(
        "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'));",
        sel, target.get_attribute("value"),
    )
    time.sleep(0.5)


def _select_single_buddy(driver, card, name_fragment: str) -> None:
    """Select a buddy in the single-mode participant dropdown."""
    sel = card.find_element(By.CSS_SELECTOR, ".buddy-participant-select")
    options = sel.find_elements(By.TAG_NAME, "option")
    target = next(o for o in options if name_fragment in o.text)
    driver.execute_script(
        "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'));",
        sel, target.get_attribute("value"),
    )
    time.sleep(0.5)


def _uncheck_participant(driver, card, name_fragment: str) -> None:
    """Uncheck a participant checkbox in group mode."""
    labels = card.find_elements(By.CSS_SELECTOR, ".buddy-participant-cb")
    label = next(l for l in labels if name_fragment in l.text)
    cb = label.find_element(By.TAG_NAME, "input")
    if cb.is_selected():
        driver.execute_script("arguments[0].click();", cb)
        time.sleep(0.5)


def _set_participant_slider(driver, card, sidx: int, pct: float) -> None:
    """Set participant slider at data-sidx to the given percentage."""
    slider = card.find_element(
        By.CSS_SELECTOR, f'.buddy-slider-row[data-sidx="{sidx}"] input[type=range]'
    )
    driver.execute_script(
        "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input'));",
        slider, str(pct),
    )
    time.sleep(0.3)


def _confirm(driver) -> None:
    """Click the Save button and wait for the success state."""
    driver.find_element(By.ID, "confirm-btn").click()
    time.sleep(2)
    assert "saved" in driver.page_source.lower() or "created" in driver.current_url, \
        f"Confirm did not reach success state. URL: {driver.current_url}"


# ---------------------------------------------------------------------------
# Module-scoped shared test data (UI setup only)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w, first_name="Schanzenfest", last_name="Tester")

    c["project_uid"] = _ui_create_project(
        driver, "Schanzenfest 2026",
        description="Gemeinsame Ausgaben rund ums Schanzenfest in Altschauerberg.",
    )
    _ui_upload_picture(driver, c["project_uid"])
    _ui_add_dummy(driver, c["project_uid"], "Volker Sauerbier")
    _ui_add_dummy(driver, c["project_uid"], "Andreas Krawall")
    # Personal offline buddy required for the Direct Buddy tab to appear
    _ui_add_personal_dummy(driver, "Volker Sauerbier")

    # Shell: read-only, needed for assertion lookups
    c["me_pk"] = _get_pk(c["email"])
    c["dummy1_pk"] = _get_dummy_pk(c["project_uid"], "Volker Sauerbier")
    c["dummy2_pk"] = _get_dummy_pk(c["project_uid"], "Andreas Krawall")
    c["personal_dummy1_pk"] = _get_personal_dummy_pk(c["email"], "Volker Sauerbier")

    yield c
    cleanup_user(c["email"])


# ---------------------------------------------------------------------------
# 1 + 3: No project assignment
# ---------------------------------------------------------------------------

class TestExpressNoProject:
    """Keep the None tab: expense must be saved without a project."""

    def test_none_tab_saves_without_project(self, driver, w, ctx):
        """Case 1: None tab (default) -> no project."""
        if not _ui_parse(driver, "Busticket 25 Euro"):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        # None tab is the default; verify it is active
        assert "assign-tab--active" in card.find_element(
            By.CSS_SELECTOR, ".pcard-assign-none"
        ).get_attribute("class"), "None tab must be active by default"
        _confirm(driver)
        assert _expense_project_name(title, ctx["email"]) is None

    def test_switch_to_none_after_project_saves_without_project(self, driver, w, ctx):
        """Case 3: switch from Project tab back to None -> no project."""
        if not _ui_parse(driver, "Schlafsack 40 Euro"):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        _click_tab(driver, card, ".pcard-assign-project")
        _click_tab(driver, card, ".pcard-assign-none")
        _confirm(driver)
        assert _expense_project_name(title, ctx["email"]) is None


# ---------------------------------------------------------------------------
# 2: Project tab assigns project
# ---------------------------------------------------------------------------

class TestExpressWithProject:
    """Select the Project tab: expense must be saved with Schanzenfest 2026."""

    def test_project_tab_assigns_project(self, driver, w, ctx):
        """Case 2: Project tab selected -> expense gets the project."""
        if not _ui_parse(driver, "Benzin 60 Euro Anfahrt"):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        _click_tab(driver, card, ".pcard-assign-project")
        time.sleep(0.5)
        # Schanzenfest 2026 is the only project; it is pre-selected
        _confirm(driver)
        assert _expense_project_name(title, ctx["email"]) == "Schanzenfest 2026"


# ---------------------------------------------------------------------------
# 4 + 5: Direct buddy with custom shares
# ---------------------------------------------------------------------------

class TestExpressDirectBuddy:

    def test_me_payer_volker_35pct(self, driver, w, ctx):
        """Case 4: me pays, Volker gets 35%."""
        if not _ui_parse(driver, "Bierkisten 60 Euro"):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        _set_value(driver, card, "60.00")
        _click_tab(driver, card, ".pcard-assign-buddy")
        _set_payer(driver, card, "Me (")
        _select_single_buddy(driver, card, "Volker")
        _set_participant_slider(driver, card, 0, 35.0)
        _confirm(driver)

        assert _expense_in_api(title, ctx), \
            f"Me-payer expense must appear in the expense API (title={title!r})"
        spendings = _expense_spendings(title, ctx["email"])
        assert len(spendings) == 1
        s = spendings[0]
        assert s["type"] == "dummy" and s["id"] == ctx["personal_dummy1_pk"]
        assert abs(s["share"] - 35.0) < 0.01, f"Expected 35%, got {s['share']}"

    def test_volker_payer_me_40pct(self, driver, w, ctx):
        """Case 5: Volker pays (is_dummy expense), me gets 40%."""
        if not _ui_parse(driver, "Zeltmiete 60 Euro"):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        _set_value(driver, card, "60.00")
        _click_tab(driver, card, ".pcard-assign-buddy")
        _set_payer(driver, card, "Volker")
        # Me is auto-added as participant; slider at data-sidx=0
        _set_participant_slider(driver, card, 0, 40.0)
        _confirm(driver)

        assert not _expense_in_api(title, ctx), \
            f"Dummy-payer expense must not appear in the regular expense API (title={title!r})"
        spendings = _expense_spendings(title, ctx["email"])
        assert len(spendings) == 1
        s = spendings[0]
        assert s["type"] == "feuser" and s["id"] == ctx["me_pk"]
        assert abs(s["share"] - 40.0) < 0.01, f"Expected 40%, got {s['share']}"


# ---------------------------------------------------------------------------
# 6 + 7: Project with partial member selection and custom shares
# ---------------------------------------------------------------------------

class TestExpressProjectPayment:

    def test_volker_payer_andreas_excluded_me_55pct(self, driver, w, ctx):
        """Case 6: Volker pays; Andreas deselected; me gets 55%."""
        if not _ui_parse(driver, "Campingausrüstung für Schanzenfest, 60 Euro"):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        _set_value(driver, card, "60.00")
        _click_tab(driver, card, ".pcard-assign-project")
        _set_payer(driver, card, "Volker")
        _uncheck_participant(driver, card, "Andreas")
        # Only me remains as participant at index 0
        _set_participant_slider(driver, card, 0, 55.0)
        _confirm(driver)

        assert not _expense_in_api(title, ctx), \
            f"Dummy-payer project expense must not appear in the regular expense API (title={title!r})"
        assert _expense_project_name(title, ctx["email"]) == "Schanzenfest 2026"
        spendings = _expense_spendings(title, ctx["email"])
        assert len(spendings) == 1
        s = spendings[0]
        assert s["type"] == "feuser" and s["id"] == ctx["me_pk"]
        assert abs(s["share"] - 55.0) < 0.01, f"Expected 55%, got {s['share']}"

    def test_me_payer_andreas_excluded_volker_45pct(self, driver, w, ctx):
        """Case 7: me pays; Andreas deselected; Volker gets 45%."""
        if not _ui_parse(driver, "Verpflegung Schanzenfest 60 Euro"):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        _set_value(driver, card, "60.00")
        _click_tab(driver, card, ".pcard-assign-project")
        # Me is payer by default; uncheck Andreas
        _uncheck_participant(driver, card, "Andreas")
        # Volker is the only remaining participant at index 0
        _set_participant_slider(driver, card, 0, 45.0)
        _confirm(driver)

        assert _expense_in_api(title, ctx), \
            f"Me-payer project expense must appear in the expense API (title={title!r})"
        assert _expense_project_name(title, ctx["email"]) == "Schanzenfest 2026"
        spendings = _expense_spendings(title, ctx["email"])
        assert len(spendings) == 1
        s = spendings[0]
        assert s["type"] == "dummy" and s["id"] == ctx["dummy1_pk"]
        assert abs(s["share"] - 45.0) < 0.01, f"Expected 45%, got {s['share']}"
