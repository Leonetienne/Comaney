"""
Tests for the "Update expenses" button on the scheduled expense list.

Covers:
  1. The modal opens and lists generated expenses for the current year.
  2. All expenses are checked by default.
  3. Confirming the modal updates expense fields to match the scheduled expense.
  4. Deselecting an expense before confirming leaves that expense unchanged.
  5. "Select unsettled" checks only not-yet-settled expenses.

Run: pytest tests/e2e/test_scheduled_update_expenses.py -sx
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, api_get, api_post, api_delete, api_patch,
    setup_user, cleanup_user, server_today, run_cmd,
)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


def _all_expenses(ctx):
    return api_get("/api/v1/expenses/", ctx, params={"view": "year"}).json()["expenses"]


def _expenses_by_title(ctx, title):
    return [e for e in _all_expenses(ctx) if e["title"] == title]


def _open_update_modal(driver, w, sched_id):
    """Navigate to scheduled list and click Update expenses for sched_id."""
    driver.get(_url("/budget/scheduled/"))
    time.sleep(1)
    btn = w.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, f'[data-update-expenses-url*="/scheduled/{sched_id}/update-expenses/"]')
    ))
    btn.click()
    time.sleep(1)


class TestUpdateExpensesModal:

    def test_modal_opens_and_shows_expenses(self, driver, w, ctx):
        """Modal opens and lists at least one expense for the current year."""
        title = "UE Modal Open Test"
        sched_id = api_post("/api/v1/scheduled/", ctx, json={
            "title": title,
            "type": "expense",
            "value": "50.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": server_today(),
        }).json()["id"]
        time.sleep(1)

        generated = _expenses_by_title(ctx, title)
        assert len(generated) >= 1, "Expected at least one generated expense"

        _open_update_modal(driver, w, sched_id)

        # Modal must be visible
        modal = driver.find_element(By.ID, "update-exp-modal")
        assert "cdialog-visible" in modal.get_attribute("class")

        # At least one checkbox row should be present and checked by default
        checkboxes = driver.find_elements(By.CSS_SELECTOR, "#update-exp-items input[type=checkbox]")
        assert len(checkboxes) >= 1
        assert all(cb.is_selected() for cb in checkboxes)

        # OK button should be enabled
        ok_btn = driver.find_element(By.ID, "update-exp-ok")
        assert ok_btn.is_enabled()

        driver.find_element(By.ID, "update-exp-cancel").click()
        time.sleep(0.3)
        for e in generated:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sched_id}/", ctx)

    def test_update_applies_changes_to_selected_expenses(self, driver, w, ctx):
        """After editing the scheduled expense, Update expenses syncs changes to generated ones."""
        old_title = "UE Before Update"
        new_title = "UE After Update"
        today = server_today()

        sched_id = api_post("/api/v1/scheduled/", ctx, json={
            "title": old_title,
            "type": "expense",
            "value": "40.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": today,
        }).json()["id"]
        time.sleep(1)

        generated_before = _expenses_by_title(ctx, old_title)
        assert len(generated_before) >= 1

        exp_before = generated_before[0]
        assert float(exp_before["value"]) == 40.0

        # PATCH the scheduled expense to change title and value
        api_patch(f"/api/v1/scheduled/{sched_id}/", ctx, json={
            "title": new_title,
            "type": "expense",
            "value": "77.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": today,
        })
        time.sleep(0.5)

        # Existing expenses should still have old title (generation is idempotent)
        assert _expenses_by_title(ctx, old_title), "Expense should still have old title before update"

        # Open the update modal and confirm (all checked by default)
        _open_update_modal(driver, w, sched_id)

        ok_btn = w.until(EC.element_to_be_clickable((By.ID, "update-exp-ok")))
        ok_btn.click()
        time.sleep(1.5)

        # Modal should show success message
        result_el = driver.find_element(By.ID, "update-exp-result")
        assert result_el.is_displayed()
        assert "updated" in result_el.text.lower()

        driver.find_element(By.ID, "update-exp-cancel").click()
        time.sleep(0.3)

        # Expense should now have new title and value
        updated = [e for e in _all_expenses(ctx) if e["id"] == exp_before["id"]]
        assert len(updated) == 1
        assert updated[0]["title"] == new_title, f"Expected '{new_title}', got '{updated[0]['title']}'"
        assert float(updated[0]["value"]) == 77.0

        for e in _expenses_by_title(ctx, new_title):
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sched_id}/", ctx)

    def test_deselected_expense_is_not_updated(self, driver, w, ctx):
        """Unchecking an expense in the modal excludes it from the update."""
        title_before = "UE Deselect Before"
        title_after = "UE Deselect After"

        # Base date two months in the past to get at least 2 occurrences
        today = server_today()
        year, month, day = today.split("-")
        base_month = int(month) - 2
        base_year = int(year)
        if base_month < 1:
            base_month += 12
            base_year -= 1
        base_date = f"{base_year}-{base_month:02d}-{day}"

        sched_id = api_post("/api/v1/scheduled/", ctx, json={
            "title": title_before,
            "type": "expense",
            "value": "20.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": base_date,
        }).json()["id"]
        time.sleep(1)

        generated = _expenses_by_title(ctx, title_before)
        if len(generated) < 2:
            for e in generated:
                api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
            api_delete(f"/api/v1/scheduled/{sched_id}/", ctx)
            pytest.skip("Fewer than 2 generated expenses in range; skipping deselect test")

        # Sort by date_due so first row = earliest
        generated.sort(key=lambda e: e.get("date_due") or "")
        first_id = generated[0]["id"]
        second_id = generated[1]["id"]

        api_patch(f"/api/v1/scheduled/{sched_id}/", ctx, json={
            "title": title_after,
            "type": "expense",
            "value": "20.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": base_date,
        })
        time.sleep(0.5)

        _open_update_modal(driver, w, sched_id)

        checkboxes = w.until(lambda d: d.find_elements(
            By.CSS_SELECTOR, "#update-exp-items input[type=checkbox]"))
        assert len(checkboxes) >= 2

        # Uncheck the first row (earliest expense) via JS
        driver.execute_script("arguments[0].checked = false;", checkboxes[0])
        driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", checkboxes[0])
        time.sleep(0.3)

        ok_btn = w.until(EC.element_to_be_clickable((By.ID, "update-exp-ok")))
        ok_btn.click()
        time.sleep(1.5)

        driver.find_element(By.ID, "update-exp-cancel").click()
        time.sleep(0.3)

        all_by_id = {e["id"]: e for e in _all_expenses(ctx)}
        assert all_by_id[first_id]["title"] == title_before, "Deselected expense must not be updated"
        assert all_by_id[second_id]["title"] == title_after, "Selected expense must be updated"

        for e in _all_expenses(ctx):
            if e["id"] in {first_id, second_id}:
                api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sched_id}/", ctx)

    def test_select_unsettled_only_checks_unsettled_expenses(self, driver, w, ctx):
        """'Select unsettled' link checks only expenses that are not yet settled."""
        title_before = "UE Unsettled Before"
        title_after = "UE Unsettled After"

        today = server_today()
        year, month, day = today.split("-")
        base_month = int(month) - 2
        base_year = int(year)
        if base_month < 1:
            base_month += 12
            base_year -= 1
        base_date = f"{base_year}-{base_month:02d}-{day}"

        sched_id = api_post("/api/v1/scheduled/", ctx, json={
            "title": title_before,
            "type": "expense",
            "value": "30.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": base_date,
        }).json()["id"]
        time.sleep(1)

        generated = _expenses_by_title(ctx, title_before)
        if len(generated) < 2:
            for e in generated:
                api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
            api_delete(f"/api/v1/scheduled/{sched_id}/", ctx)
            pytest.skip("Fewer than 2 generated expenses in range; skipping unsettled test")

        generated.sort(key=lambda e: e.get("date_due") or "")
        settled_id = generated[0]["id"]
        unsettled_id = generated[1]["id"]

        api_patch(f"/api/v1/expenses/{settled_id}/", ctx, json={"settled": True})
        api_patch(f"/api/v1/expenses/{unsettled_id}/", ctx, json={"settled": False})
        time.sleep(0.3)

        api_patch(f"/api/v1/scheduled/{sched_id}/", ctx, json={
            "title": title_after,
            "type": "expense",
            "value": "30.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": base_date,
        })
        time.sleep(0.5)

        _open_update_modal(driver, w, sched_id)

        checkboxes = w.until(lambda d: d.find_elements(
            By.CSS_SELECTOR, "#update-exp-items input[type=checkbox]"))
        assert len(checkboxes) >= 2

        link = driver.find_element(By.ID, "update-exp-select-unsettled")
        link.click()
        time.sleep(0.3)

        checked_ids = {
            int(cb.get_attribute("data-expense-id"))
            for cb in driver.find_elements(By.CSS_SELECTOR, "#update-exp-items input[type=checkbox]")
            if cb.is_selected()
        }
        assert settled_id not in checked_ids, "Settled expense must not be checked"
        assert unsettled_id in checked_ids, "Unsettled expense must be checked"

        ok_btn = w.until(EC.element_to_be_clickable((By.ID, "update-exp-ok")))
        ok_btn.click()
        time.sleep(1.5)

        driver.find_element(By.ID, "update-exp-cancel").click()
        time.sleep(0.3)

        all_by_id = {e["id"]: e for e in _all_expenses(ctx)}
        assert all_by_id[settled_id]["title"] == title_before, "Settled expense must not be updated"
        assert all_by_id[unsettled_id]["title"] == title_after, "Unsettled expense must be updated"

        for e in _all_expenses(ctx):
            if e["id"] in {settled_id, unsettled_id}:
                api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sched_id}/", ctx)

    def test_no_expenses_shows_empty_state(self, driver, w, ctx):
        """Modal shows a message when no expenses exist for the current year."""
        sched_id = api_post("/api/v1/scheduled/", ctx, json={
            "title": "UE Empty State",
            "type": "expense",
            "value": "5.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": "2099-01-01",
        }).json()["id"]
        time.sleep(0.5)

        _open_update_modal(driver, w, sched_id)

        status_el = driver.find_element(By.ID, "update-exp-status")
        assert status_el.is_displayed()
        assert "no expenses" in status_el.text.lower()

        ok_btn = driver.find_element(By.ID, "update-exp-ok")
        assert not ok_btn.is_enabled()

        driver.find_element(By.ID, "update-exp-cancel").click()
        api_delete(f"/api/v1/scheduled/{sched_id}/", ctx)
