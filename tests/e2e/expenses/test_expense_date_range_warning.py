"""
Expense form: warns when the expense's date falls outside the currently
selected global date range (localStorage `comaney_date_range`), mirroring the
existing upfront-payer confirm dialog (see tests/e2e/buddies/test_expense_form.py).
Covers both create and edit.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, api_get, api_post, server_today

_OUT_OF_RANGE_FROM = "2020-01-01"
_OUT_OF_RANGE_TO = "2020-01-31"


def _set_range(driver, date_from, date_to):
    driver.execute_script(
        "localStorage.setItem('comaney_date_range', JSON.stringify("
        f"{{from:'{date_from}', to:'{date_to}'}}));"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w, first_name="Range", last_name="Warner")
    yield c
    cleanup_user(c["email"])


# ---------------------------------------------------------------------------
# Create: out-of-range date
# ---------------------------------------------------------------------------

class TestDateOutsideRangeWarningOnCreate:
    """Creating an expense whose date falls outside the selected display
    period must show a confirmation dialog before saving."""

    def test_dialog_appears_for_out_of_range_date(self, driver, w, ctx):
        _set_range(driver, _OUT_OF_RANGE_FROM, _OUT_OF_RANGE_TO)
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("Out Of Range Expense")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("12.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(0.5)
        backdrop = driver.find_element(By.ID, "cdialog-backdrop")
        assert "cdialog-visible" in backdrop.get_attribute("class")
        msg = driver.find_element(By.ID, "cdialog-msg").text
        assert _OUT_OF_RANGE_FROM in msg and _OUT_OF_RANGE_TO in msg

    def test_cancel_keeps_expense_unsaved(self, driver, w, ctx):
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert "/budget/expenses/new/" in driver.current_url
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Out Of Range Expense"})
        assert not any(e["title"] == "Out Of Range Expense" for e in resp.json()["expenses"]), \
            "Expense must not be created while the warning dialog is pending/cancelled"

    def test_confirm_saves_the_expense(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert "/budget/expenses/" in driver.current_url
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Out Of Range Expense"})
        assert any(e["title"] == "Out Of Range Expense" for e in resp.json()["expenses"]), \
            "Confirming the dialog must still save the expense"


# ---------------------------------------------------------------------------
# Create: in-range date (regression - no dialog)
# ---------------------------------------------------------------------------

class TestDateInsideRangeNoWarning:
    """An expense whose date falls inside the selected range is saved
    immediately, with no confirmation dialog in the way."""

    def test_no_dialog_for_in_range_date(self, driver, w, ctx):
        today = server_today()
        _set_range(driver, today, today)
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("In Range Expense")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("8.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(1.5)
        assert "/budget/expenses/" in driver.current_url, \
            "Submit must go straight through with no dialog when the date is in range"
        backdrop_classes = driver.execute_script(
            "var b = document.getElementById('cdialog-backdrop');"
            "return b ? b.className : '';"
        )
        assert "cdialog-visible" not in backdrop_classes


# ---------------------------------------------------------------------------
# Edit: moving the date out of range
# ---------------------------------------------------------------------------

class TestDateOutsideRangeWarningOnEdit:
    """Editing an expense and changing its date to fall outside the selected
    display range triggers the same confirmation dialog as on create."""

    @pytest.fixture(scope="class")
    def exp_id(self, driver, w, ctx):
        today = server_today()
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "Edit Range Expense",
            "value": "5.00",
            "type": "expense",
            "date_due": today,
            "settled": True,
        })
        return resp.json()["id"]

    def test_no_dialog_when_date_stays_in_range(self, driver, w, ctx, exp_id):
        today = server_today()
        _set_range(driver, today, today)
        driver.get(_url(f"/budget/expenses/{exp_id}/edit/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(1.5)
        assert "/budget/expenses/" in driver.current_url

    def test_dialog_appears_when_moving_date_out_of_range(self, driver, w, ctx, exp_id):
        driver.get(_url(f"/budget/expenses/{exp_id}/edit/"))
        time.sleep(1)
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{_OUT_OF_RANGE_FROM}';"
        )
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(0.5)
        backdrop = driver.find_element(By.ID, "cdialog-backdrop")
        assert "cdialog-visible" in backdrop.get_attribute("class")

    def test_confirm_saves_the_new_date(self, driver, w, ctx, exp_id):
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        resp = api_get("/api/v1/expenses/", ctx, params={
            "q": "Edit Range Expense",
            "date_from": "2019-01-01",
            "date_to": "2021-01-01",
        })
        matches = [e for e in resp.json()["expenses"] if e["id"] == exp_id]
        assert matches, "Edited expense not found via API with the wider date range"
        assert matches[0]["date_due"] == _OUT_OF_RANGE_FROM
