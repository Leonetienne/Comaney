"""
AI Express Creation: date-range warning dialog.

Mirrors the personal expense form's behaviour (see
tests/e2e/expenses/test_expense_date_range_warning.py): saving an item whose
date falls outside the currently selected global display range shows a
confirmation dialog before the batch is submitted.

Skips gracefully when the AI trial key is not configured/exhausted, same as
the rest of the Express Creation suite (tests/e2e/express/test_express.py).
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, api_get, api_delete, setup_user, cleanup_user

AI_TIMEOUT = 120
# The selected display range (2020-01) and the forced item date (2024-05-01)
# must be disjoint: that mismatch is exactly what the warning checks for.
_OUT_OF_RANGE_DATE = "2024-05-01"
_OUT_OF_RANGE_FROM = "2020-01-01"
_OUT_OF_RANGE_TO = "2020-01-31"


def _set_range(driver, date_from, date_to):
    driver.execute_script(
        "localStorage.setItem('comaney_date_range', JSON.stringify("
        f"{{from:'{date_from}', to:'{date_to}'}}));"
    )


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
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestExpressCreationDateRangeWarning:

    def test_trial_available(self, driver, w, ctx):
        if not _trial_available(driver):
            pytest.skip("AI trial not available in this environment")
        ctx["trial_ok"] = True

    def test_dialog_appears_for_out_of_range_item(self, driver, w, ctx):
        if not ctx.get("trial_ok"):
            pytest.skip("Trial not available")
        _set_range(driver, _OUT_OF_RANGE_FROM, _OUT_OF_RANGE_TO)
        driver.get(_url("/budget/ai/express-creation/"))
        time.sleep(1)
        ta = driver.find_element(By.CSS_SELECTOR, "textarea[name=description]")
        driver.execute_script("arguments[0].value = 'Coffee 3 euros';", ta)
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

        # Force a known out-of-range date regardless of what the AI picked,
        # so the test doesn't depend on the AI's date inference.
        driver.execute_script(
            f"document.querySelectorAll('.preview-card .edit-date')"
            f".forEach(el => el.value = '{_OUT_OF_RANGE_DATE}');"
        )
        driver.find_element(By.ID, "confirm-btn").click()
        time.sleep(0.5)
        backdrop = driver.find_element(By.ID, "cdialog-backdrop")
        assert "cdialog-visible" in backdrop.get_attribute("class")
        msg = driver.find_element(By.ID, "cdialog-msg").text
        assert _OUT_OF_RANGE_FROM in msg and _OUT_OF_RANGE_TO in msg

    def test_cancel_keeps_batch_unsaved(self, driver, w, ctx):
        if not ctx.get("trial_ok"):
            pytest.skip("Trial not available")
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert not driver.find_elements(By.CSS_SELECTOR, ".success-banner")
        resp = api_get("/api/v1/expenses/", ctx, params={
            "date_from": "2024-01-01", "date_to": "2024-12-31",
        })
        assert not any(e["date_due"] == _OUT_OF_RANGE_DATE for e in resp.json()["expenses"])

    def test_confirm_saves_despite_warning(self, driver, w, ctx):
        if not ctx.get("trial_ok"):
            pytest.skip("Trial not available")
        driver.find_element(By.ID, "confirm-btn").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(5)
        assert driver.find_elements(By.CSS_SELECTOR, ".success-banner")
        resp = api_get("/api/v1/expenses/", ctx, params={
            "date_from": "2024-01-01", "date_to": "2024-12-31",
        })
        matches = [e for e in resp.json()["expenses"] if e["date_due"] == _OUT_OF_RANGE_DATE]
        assert matches, "Expense with the out-of-range date was not created"
        for e in matches:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
