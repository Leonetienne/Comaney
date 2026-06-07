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
  8. AI participation: description drops Andreas -> Andreas excluded from split
  9. AI participation: description pins Andreas to 0% -> Andreas kept at 0%
 10. View-expenses link: all-project batch -> links to /projects/<uid>/
 11. View-expenses link: all-direct-buddy batch -> links to /buddies/summary/
 12. AI upfront payer: description says Volker paid -> Volker is the payer
 13. AI direct buddy: description shares one-on-one with Kevin -> direct buddy expense
"""
import os
import re
import subprocess
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, api_get, setup_user, cleanup_user

DOCKER_WEB = "comaney-web-1"
ASSET = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "projectpic.jpg")
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


def _expense_upfront_dummy_pk(title: str, owner_email: str) -> int | None:
    result = _shell(
        f"from budget.models import Expense; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"e = Expense.objects.filter(title__startswith='{title}', owning_feuser=u).first(); "
        f"print(e.upfront_payee_dummy_id if e and e.upfront_payee_dummy_id else 'None')"
    )
    return None if result == "None" else int(result)


def _expense_in_api(title_prefix: str, ctx: dict) -> bool:
    """
    True if the most recently created expense matching this title prefix appears
    in the regular expense API. Scoped to that one expense's id (not just any
    title match) because several test cases in this module create similarly
    AI-titled "Camping..." expenses against the same shared ctx user -- an
    older, unrelated, still-visible expense with a coincidentally matching
    title would otherwise produce a false positive here.
    """
    eid = _shell(
        f"from budget.models import Expense; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{ctx['email']}'); "
        f"e = Expense.objects.filter(title__startswith='{title_prefix}', owning_feuser=u).first(); "
        f"print(e.uid if e else 'None')"
    )
    if eid == "None":
        return False
    expenses = api_get("/api/v1/expenses/", ctx, params={"q": title_prefix}).json().get("expenses", [])
    return any(e["id"] == int(eid) for e in expenses)


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


def _view_expenses_href(driver) -> str:
    """Read the href of the success banner's 'View expenses' link."""
    return driver.find_element(
        By.CSS_SELECTOR, ".success-banner a"
    ).get_attribute("href")


def _project_tab_active(card) -> bool:
    return "assign-tab--active" in card.find_element(
        By.CSS_SELECTOR, ".pcard-assign-project"
    ).get_attribute("class")


def _buddy_tab_active(card) -> bool:
    els = card.find_elements(By.CSS_SELECTOR, ".pcard-assign-buddy")
    return bool(els) and "assign-tab--active" in els[0].get_attribute("class")


def _keep_only_first_card(driver) -> None:
    """Deselect every card but the first, so the saved batch is exactly one
    expense regardless of whether the AI split the description into several."""
    cards = driver.find_elements(By.CSS_SELECTOR, ".preview-card")
    for card in cards[1:]:
        cb = card.find_element(By.CSS_SELECTOR, "input[name=selected]")
        if cb.is_selected():
            driver.execute_script("arguments[0].click();", cb)
    time.sleep(0.3)


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
    # A personal-only buddy who is NOT in any project, so the AI can assign a
    # direct buddy expense unambiguously (Volker also being a project member).
    _ui_add_personal_dummy(driver, "Kevin Klobrille")

    # Shell: read-only, needed for assertion lookups
    c["me_pk"] = _get_pk(c["email"])
    c["dummy1_pk"] = _get_dummy_pk(c["project_uid"], "Volker Sauerbier")
    c["dummy2_pk"] = _get_dummy_pk(c["project_uid"], "Andreas Krawall")
    c["personal_dummy1_pk"] = _get_personal_dummy_pk(c["email"], "Volker Sauerbier")
    c["personal_kevin_pk"] = _get_personal_dummy_pk(c["email"], "Kevin Klobrille")

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


# ---------------------------------------------------------------------------
# 8 + 9: AI-supplied participation overrides (no manual UI participant edits)
# ---------------------------------------------------------------------------

class TestExpressAiParticipation:
    """The AI encodes participation exceptions straight from the description.

    These drive only the parse + confirm; the participant selection / shares
    must come from the AI's project_participants output, applied automatically
    when the project card opens.
    """

    def test_ai_excludes_member(self, driver, w, ctx):
        """Case 8: 'Andreas macht nicht mit' -> Andreas dropped from the split."""
        desc = ("Campingausruestung fuer das Schanzenfest 2026, 60 Euro. "
                "Andreas macht bei dieser Ausgabe nicht mit, alle anderen teilen sich das.")
        if not _ui_parse(driver, desc):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        if not _project_tab_active(card):
            pytest.skip("AI did not assign the project; participation override not applicable")
        _confirm(driver)

        assert _expense_project_name(title, ctx["email"]) == "Schanzenfest 2026"
        spendings = _expense_spendings(title, ctx["email"])
        ids = {(s["type"], s["id"]) for s in spendings}
        assert ("dummy", ctx["dummy2_pk"]) not in ids, \
            f"Andreas should be excluded by the AI, got {spendings}"
        assert ("dummy", ctx["dummy1_pk"]) in ids, \
            f"Volker should still share the cost, got {spendings}"

    def test_ai_pins_member_to_zero(self, driver, w, ctx):
        """Case 9: 'Andreas geht auf uns, 0%' -> Andreas kept, share 0."""
        desc = ("Verpflegung fuers Schanzenfest 2026, 60 Euro. "
                "Andreas geht auf uns, setz seinen Anteil auf 0 Prozent.")
        if not _ui_parse(driver, desc):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        if not _project_tab_active(card):
            pytest.skip("AI did not assign the project; participation override not applicable")
        _confirm(driver)

        assert _expense_project_name(title, ctx["email"]) == "Schanzenfest 2026"
        spendings = _expense_spendings(title, ctx["email"])
        andreas = next(
            (s for s in spendings if s["type"] == "dummy" and s["id"] == ctx["dummy2_pk"]),
            None,
        )
        assert andreas is not None, \
            f"Andreas should still be a participant at 0%, got {spendings}"
        assert abs(andreas["share"]) < 0.01, \
            f"Andreas should be pinned to 0%, got {andreas['share']}"

    def test_ai_sets_upfront_payer(self, driver, w, ctx):
        """Case 12: 'Volker hat bezahlt' -> Volker is the upfront payer."""
        desc = ("Volker hat die Campingausruestung fuers Schanzenfest 2026 bezahlt, "
                "60 Euro. Wir teilen uns die Kosten.")
        if not _ui_parse(driver, desc):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        if not _project_tab_active(card):
            pytest.skip("AI did not assign the project; payer override not applicable")
        _confirm(driver)

        assert _expense_project_name(title, ctx["email"]) == "Schanzenfest 2026"
        # A dummy-paid expense is owned by me but does not show in the regular list.
        assert not _expense_in_api(title, ctx), \
            f"Dummy-payer project expense must not appear in the expense API (title={title!r})"
        assert _expense_upfront_dummy_pk(title, ctx["email"]) == ctx["dummy1_pk"], \
            "Volker should be recorded as the upfront payer"
        spendings = _expense_spendings(title, ctx["email"])
        ids = {(s["type"], s["id"]) for s in spendings}
        assert ("dummy", ctx["dummy1_pk"]) not in ids, \
            f"The payer (Volker) must not also be a participant, got {spendings}"


# ---------------------------------------------------------------------------
# 13: AI-assigned direct (one-on-one) buddy expense
# ---------------------------------------------------------------------------

class TestExpressAiDirectBuddy:
    """The AI can route an expense to a one-on-one direct buddy from the text."""

    def test_ai_assigns_direct_buddy(self, driver, w, ctx):
        """Case 13: 'mit Kevin geteilt' -> direct buddy expense with Kevin."""
        desc = ("Ich war mit Kevin Klobrille zu zweit Kaffee trinken, 8 Euro. "
                "Ich habe bezahlt, wir teilen uns die Kosten 50/50. "
                "Das hat nichts mit dem Schanzenfest zu tun.")
        if not _ui_parse(driver, desc):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        title = _card_title(card)
        if not _buddy_tab_active(card):
            pytest.skip("AI did not assign a direct buddy")
        _confirm(driver)

        # A direct buddy expense is personal (no project) and I am the payer.
        assert _expense_project_name(title, ctx["email"]) is None
        spendings = _expense_spendings(title, ctx["email"])
        kevin = next(
            (s for s in spendings if s["type"] == "dummy" and s["id"] == ctx["personal_kevin_pk"]),
            None,
        )
        assert kevin is not None, \
            f"Kevin should be the shared direct buddy, got {spendings}"
        assert kevin["share"] > 0, f"Kevin should owe a share, got {spendings}"


# ---------------------------------------------------------------------------
# 10 + 11: "View expenses" success-link routing
# ---------------------------------------------------------------------------

class TestExpressViewExpensesLink:
    """The success banner routes to the most relevant place for the batch."""

    def test_all_project_links_to_project(self, driver, w, ctx):
        """Case 10: a single project expense -> link points to /projects/<uid>/."""
        if not _ui_parse(driver, "Stromgenerator 60 Euro"):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        _keep_only_first_card(driver)
        _click_tab(driver, card, ".pcard-assign-project")
        time.sleep(0.5)
        _confirm(driver)
        href = _view_expenses_href(driver)
        assert href.rstrip("/").endswith(f"/projects/{ctx['project_uid']}"), \
            f"Expected the project detail link, got {href!r}"

    def test_all_direct_buddy_links_to_summary(self, driver, w, ctx):
        """Case 11: a single direct-buddy expense -> link points to /buddies/summary/."""
        if not _ui_parse(driver, "Pizza 30 Euro"):
            pytest.skip("AI unavailable")
        card = _first_card(driver)
        _keep_only_first_card(driver)
        _click_tab(driver, card, ".pcard-assign-buddy")
        _set_payer(driver, card, "Me (")
        _select_single_buddy(driver, card, "Volker")
        _confirm(driver)
        href = _view_expenses_href(driver)
        assert href.rstrip("/").endswith("/buddies/summary"), \
            f"Expected the buddy summary link, got {href!r}"
