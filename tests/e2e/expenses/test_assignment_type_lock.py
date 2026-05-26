"""
Reactive lock between the expense `type` field and the "Expense assignment"
section on the create form (budget/templates/budget/partials/_expense_assignment.html):
type != expense hides/clears the assignment, and an active assignment locks
the type dropdown to "Expense". The two can never end up in conflict because
each direction blocks the other from being set first.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _create_group, _shell


class TestExpenseTypeAssignmentLock:

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="Locky", last_name="Tester")
        email = user["email"]
        group_id = int(_create_group(email, "Type Lock Project"))
        yield {**user, "group_id": group_id}
        cleanup_user(email)

    def _open_form(self, driver):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1.5)

    def _set_type(self, driver, value):
        driver.execute_script(
            "var sel = document.getElementById('id_type');"
            "sel.value = arguments[0];"
            "sel.dispatchEvent(new Event('change', {bubbles: true}));",
            value,
        )
        time.sleep(0.3)

    def _type_option_disabled(self, driver, value):
        return driver.execute_script(
            "var sel = document.getElementById('id_type');"
            "var target = arguments[0];"
            "var opt = Array.from(sel.options).find(function(o){return o.value === target;});"
            "return opt ? opt.disabled : null;",
            value,
        )

    def _assignment_block_visible(self, driver):
        return driver.execute_script(
            "var el = document.getElementById('expense-assignment-block');"
            "return el ? window.getComputedStyle(el).display !== 'none' : null;"
        )

    def _select_project(self, driver, group_id):
        driver.find_element(By.ID, "assign-project").click()
        time.sleep(0.3)
        sel = driver.find_element(By.ID, "buddy-group-select")
        driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('change'));",
            sel, str(group_id),
        )
        time.sleep(0.5)

    def test_assignment_visible_by_default(self, driver, w, ctx):
        self._open_form(driver)
        assert self._assignment_block_visible(driver) is True, \
            "Expense assignment must be visible while type=Expense"
        assert self._type_option_disabled(driver, "income") is False, \
            "Type options must be unlocked while assignment is none"

    def test_income_hides_assignment(self, driver, w, ctx):
        self._set_type(driver, "income")
        assert self._assignment_block_visible(driver) is False, \
            "Expense assignment must hide when type != Expense"

    def test_switching_back_to_expense_shows_assignment(self, driver, w, ctx):
        self._set_type(driver, "expense")
        assert self._assignment_block_visible(driver) is True, \
            "Expense assignment must reappear when type is switched back to Expense"

    def test_project_assignment_locks_type_dropdown(self, driver, w, ctx):
        self._select_project(driver, ctx["group_id"])
        cb = driver.find_element(By.ID, "buddy-payment-cb")
        assert cb.is_selected(), "Setup: project assignment must be active"
        assert self._type_option_disabled(driver, "income") is True, \
            "Non-expense type options must be disabled while an assignment is active"
        assert self._type_option_disabled(driver, "savings_dep") is True
        assert self._type_option_disabled(driver, "expense") is False, \
            "Expense itself must stay selectable"

    def test_clearing_assignment_unlocks_type_dropdown(self, driver, w, ctx):
        driver.find_element(By.ID, "assign-none").click()
        time.sleep(0.3)
        assert self._type_option_disabled(driver, "income") is False, \
            "Type options must unlock once the assignment is cleared"

    def test_changing_type_away_forces_assignment_off(self, driver, w, ctx):
        self._select_project(driver, ctx["group_id"])
        cb = driver.find_element(By.ID, "buddy-payment-cb")
        assert cb.is_selected(), "Setup: assignment must be active before testing the force-off"
        self._set_type(driver, "income")
        assert not cb.is_selected(), "Changing type away from Expense must clear the assignment"
        assert self._assignment_block_visible(driver) is False


class TestExpenseEditTypeAssignmentLockOnLoad:
    """The same lock must already be in effect on page load for the (prefilled)
    edit form, not just after a user interaction."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="LockyEdit", last_name="Tester")
        email = user["email"]
        group_id = int(_create_group(email, "Edit Type Lock Project"))
        exp_uid = int(_shell(
            f"from budget.expense_factory import create_expense; from budget.models import TransactionType; "
            f"from feusers.models import FeUser; from buddies.models import Project; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); g = Project.objects.get(pk={group_id}); "
            f"e = create_expense(owning_feuser=u, title='EditLockExpense', type=TransactionType.EXPENSE, "
            f"value=Decimal('5.00'), project=g, buddy_spendings=[]); print(e.uid)"
        ))
        yield {**user, "group_id": group_id, "exp_uid": exp_uid}
        cleanup_user(email)

    def _type_option_disabled(self, driver, value):
        return driver.execute_script(
            "var sel = document.getElementById('id_type');"
            "var target = arguments[0];"
            "var opt = Array.from(sel.options).find(function(o){return o.value === target;});"
            "return opt ? opt.disabled : null;",
            value,
        )

    def test_type_dropdown_already_locked_on_load(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_uid']}/edit/"))
        time.sleep(1.5)
        assert self._type_option_disabled(driver, "income") is True, \
            "Editing a project expense must start with non-expense types already disabled"
        assert self._type_option_disabled(driver, "expense") is False
