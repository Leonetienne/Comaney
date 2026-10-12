"""
AI Express Creation: missing category/tags warning.

Same warning as the manual expense form (see
tests/e2e/expenses/test_unclassified_save_warning.py): saving a selected item
without a category or tags asks first; one dialog covers every item.

Skips gracefully when the AI trial key is not configured/exhausted, same as
the rest of the Express Creation suite (tests/e2e/express/test_express.py).
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, ai_unavailable, api_delete, api_get, cleanup_user, setup_user

AI_TIMEOUT = 120
WARNING_TEXT = "You are missing a category or tags"
TITLE = "Express Warn Coffee"


def _trial_available(driver):
    driver.get(_url("/budget/ai/express-creation/"))
    time.sleep(1)
    if "/profile" in driver.current_url:
        return False
    src = driver.page_source
    if "temporarily unavailable" in src or "Monthly AI limit reached" in src:
        return False
    if driver.find_elements(By.CSS_SELECTOR, ".trial-blocked"):
        return False
    return True


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w, unclassified_warning=True)
    yield c
    cleanup_user(c["email"])


def _dialog_visible(driver) -> bool:
    return "cdialog-visible" in driver.find_element(By.ID, "cdialog-backdrop").get_attribute("class")


class TestExpressCreationUnclassifiedWarning:

    def test_trial_available(self, driver, w, ctx):
        if not _trial_available(driver):
            ai_unavailable("AI trial not available in this environment")
        ctx["trial_ok"] = True

    def test_dialog_appears_for_item_without_tags(self, driver, w, ctx):
        if not ctx.get("trial_ok"):
            ai_unavailable("Trial not available")
        driver.execute_script("localStorage.removeItem('comaney_date_range');")
        driver.get(_url("/budget/ai/express-creation/"))
        time.sleep(1)
        ta = driver.find_element(By.CSS_SELECTOR, "textarea[name=description]")
        driver.execute_script("arguments[0].value = 'Coffee 3 euros today';", ta)
        driver.find_element(By.ID, "parse-btn").click()

        deadline = time.time() + AI_TIMEOUT
        cards = []
        while time.time() < deadline:
            cards = driver.find_elements(By.CSS_SELECTOR, ".preview-card")
            if cards:
                break
            time.sleep(3)
        if not cards:
            pytest.fail("AI response timed out: no .preview-card appeared")

        # Force a known unclassified state regardless of what the AI picked.
        driver.execute_script(
            "document.querySelectorAll('.preview-card').forEach(function (card) {"
            f"    card.querySelector('.edit-title').value = '{TITLE}';"
            "    card.querySelector('.edit-type').value = 'expense';"
            "    var cat = card.querySelector('.edit-category');"
            "    cat.value = cat.options[1].value;"
            "    card.querySelectorAll('.edit-tag-cb').forEach(function (cb) { cb.checked = false; });"
            "});"
        )
        driver.find_element(By.ID, "confirm-btn").click()
        time.sleep(0.7)
        assert _dialog_visible(driver)
        assert WARNING_TEXT in driver.find_element(By.ID, "cdialog-msg").text

    def test_cancel_keeps_batch_unsaved(self, driver, w, ctx):
        if not ctx.get("trial_ok"):
            ai_unavailable("Trial not available")
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert not driver.find_elements(By.CSS_SELECTOR, ".success-banner")
        resp = api_get("/api/v1/expenses/", ctx, params={"q": TITLE})
        assert not any(e["title"] == TITLE for e in resp.json()["expenses"])

    def test_save_anyway_saves(self, driver, w, ctx):
        if not ctx.get("trial_ok"):
            ai_unavailable("Trial not available")
        driver.find_element(By.ID, "confirm-btn").click()
        time.sleep(0.7)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(5)
        assert driver.find_elements(By.CSS_SELECTOR, ".success-banner")
        resp = api_get("/api/v1/expenses/", ctx, params={"q": TITLE})
        matches = [e for e in resp.json()["expenses"] if e["title"] == TITLE]
        assert matches, "Saving anyway must still create the expense"
        for e in matches:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
