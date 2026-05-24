"""
AI-assisted dashboard card creation/editing.

Visibility/error-envelope tests use a fake per-user API key (no real network call),
and always clear it again so later tests see the environment's true baseline.
The actual generate-flow test makes a real AI call and skips gracefully when no
usable key (own or trial) is configured -- same pattern as tests/e2e/express/test_express.py.
"""
import time

import requests
import pytest
from selenium.webdriver.common.by import By

from helpers import _url, run_cmd, setup_user, cleanup_user, session_cookies, BASE_URL, fill

AI_URL = BASE_URL + "/budget/dashboard/cards/ai/"
CARDS_URL = BASE_URL + "/budget/dashboard/cards/"
AI_TIMEOUT = 120


def _set_fake_api_key(email: str) -> None:
    run_cmd(
        "shell", "-c",
        f"from feusers.models import FeUser; u = FeUser.objects.get(email='{email}'); "
        f"u.anthropic_api_key = 'sk-test-fake-key'; "
        f"u.save(update_fields=['anthropic_api_key'])",
    )


def _clear_api_key(email: str) -> None:
    run_cmd(
        "shell", "-c",
        f"from feusers.models import FeUser; u = FeUser.objects.get(email='{email}'); "
        f"u.anthropic_api_key = ''; "
        f"u.save(update_fields=['anthropic_api_key'])",
    )


def _set_disable_ai_ui(email: str, value: bool) -> None:
    run_cmd(
        "shell", "-c",
        f"from feusers.models import FeUser; u = FeUser.objects.get(email='{email}'); "
        f"u.disable_ai_ui = {value}; "
        f"u.save(update_fields=['disable_ai_ui'])",
    )


def _cm_text(driver, backdrop_id: str) -> str:
    return driver.execute_script(
        "const el = document.querySelector('#' + arguments[0] + ' .cm-content');"
        "return el ? el.textContent : '';",
        backdrop_id,
    )


def _open_add_dialog(driver, w):
    driver.get(_url("/budget/"))
    time.sleep(3)
    driver.find_element(By.XPATH, "//button[contains(text(),'New dashboard card')]").click()
    time.sleep(1)


def _ai_available(driver) -> bool:
    """True if a real AI call could succeed: own key or a working trial key."""
    driver.get(_url("/budget/"))
    time.sleep(2)
    return len(driver.find_elements(By.CSS_SELECTOR, ".dash-ai-section")) > 0


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def sess(driver, ctx):
    driver.get(_url("/budget/"))
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


def _csrf(sess) -> str:
    return next((c.value for c in sess.cookies if c.name == "csrftoken"), "")


@pytest.fixture
def with_fake_key(ctx):
    """Give the user a (non-functional) own API key, then clear it again so
    later tests see the environment's true baseline (no own key)."""
    _set_fake_api_key(ctx["email"])
    yield
    _clear_api_key(ctx["email"])


class TestVisibility:

    def test_hidden_without_any_key(self, driver, w, ctx):
        """Fresh user with neither an own key nor a trial available: section absent."""
        if _ai_available(driver):
            pytest.skip("AI trial key is configured in this environment; cannot test the no-key case")
        assert not driver.find_elements(By.CSS_SELECTOR, ".dash-ai-section")

    def test_visible_with_own_key(self, driver, w, ctx, with_fake_key):
        driver.get(_url("/budget/"))
        time.sleep(2)
        driver.find_element(By.XPATH, "//button[contains(text(),'New dashboard card')]").click()
        time.sleep(1)
        section = driver.find_element(By.CSS_SELECTOR, "#dash-add-backdrop .dash-ai-section")
        assert section.is_displayed()
        assert "let AI create the card for you" in driver.page_source
        placeholder = driver.find_element(
            By.CSS_SELECTOR, "#dash-add-backdrop .dash-ai-input"
        ).get_attribute("placeholder")
        assert "amazon" in placeholder.lower()
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)

    def test_hidden_when_disable_ai_ui(self, driver, w, ctx, with_fake_key):
        _set_disable_ai_ui(ctx["email"], True)
        try:
            driver.get(_url("/budget/"))
            time.sleep(2)
            assert not driver.find_elements(By.CSS_SELECTOR, ".dash-ai-section")
        finally:
            _set_disable_ai_ui(ctx["email"], False)

    def test_edit_modal_placeholder_differs(self, driver, w, ctx, sess, with_fake_key):
        csrf = _csrf(sess)
        r = sess.post(CARDS_URL, json={
            "yaml_config": "type: cell\ntitle: AIPlaceholderTest\nmethod: sum\n"
                           "positioning:\n  position: 1\n  width: 2\n  height: 1\n",
        }, headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        driver.get(_url("/budget/"))
        time.sleep(3)
        driver.execute_script(
            "Array.from(document.querySelectorAll('.dash-card')).find("
            "  c => c.querySelector('.dash-card-title')?.textContent?.trim() === 'AIPlaceholderTest'"
            ")?.querySelector('.dash-card-edit-btn')?.click()"
        )
        time.sleep(1)
        placeholder = driver.find_element(
            By.CSS_SELECTOR, "#dash-edit-backdrop .dash-ai-input"
        ).get_attribute("placeholder")
        assert placeholder == "Modify this card to ..."
        driver.find_element(
            By.XPATH, "//div[@id='dash-edit-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)
        sess.delete(f"{CARDS_URL}{card_id}/", headers={"X-CSRFToken": csrf})


class TestErrorEnvelope:

    def test_missing_description_returns_400(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = sess.post(AI_URL, json={}, headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
        assert r.status_code == 400

    def test_blocked_for_disable_ai_ui(self, driver, w, ctx, sess):
        _set_disable_ai_ui(ctx["email"], True)
        try:
            csrf = _csrf(sess)
            r = sess.post(AI_URL, json={"description": "groceries this month"},
                          headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})
            assert r.status_code == 403
        finally:
            _set_disable_ai_ui(ctx["email"], False)


class TestGenerateFlow:

    def test_generate_fills_editor_without_saving(self, driver, w, ctx, sess):
        if not _ai_available(driver):
            pytest.skip("No usable AI key (own or trial) configured in this environment")

        before_count = len(sess.get(CARDS_URL).json()["cards"])

        _open_add_dialog(driver, w)
        fill(w, By.CSS_SELECTOR, "#dash-add-backdrop .dash-ai-input",
             "Show how much I spent in total this month as a single number.")
        driver.find_element(By.CSS_SELECTOR, "#dash-add-backdrop .dash-ai-section button").click()

        deadline = time.time() + AI_TIMEOUT
        note = ""
        while time.time() < deadline:
            notes = driver.find_elements(By.CSS_SELECTOR, "#dash-add-backdrop .dash-ai-note")
            if notes and notes[0].is_displayed() and notes[0].text.strip():
                note = notes[0].text
                break
            time.sleep(3)
        assert note, "AI generate timed out: no success note appeared"
        assert "Create" in note
        assert "type:" in _cm_text(driver, "dash-add-backdrop")

        # Cancel without saving -- the card must not have been created server-side.
        driver.find_element(
            By.XPATH, "//div[@id='dash-add-backdrop']//button[text()='Cancel']"
        ).click()
        time.sleep(1)
        after_count = len(sess.get(CARDS_URL).json()["cards"])
        assert after_count == before_count
