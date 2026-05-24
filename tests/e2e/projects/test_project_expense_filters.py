"""
Project expense list filters: search bar, hide recurring, only show what I paid, sort.

Setup: two users (admin A and member B) share a project with several expenses.
All expense titles use the prefix "PFilt" so existing data never interferes.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as,
    _create_group, _add_group_member, _create_group_expense,
)

PREFIX = "PFilt"


def _create_project_expense(admin_email, participant_email, group_id,
                              title, value="50.00", approved=True, recurring=False):
    """Create a project expense, optionally linked to a scheduled expense."""
    approved_val = "True" if approved else "False"
    exp_pk = _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending, Project; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"a = FeUser.objects.get(email='{admin_email}'); "
        f"b = FeUser.objects.get(email='{participant_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"e = Expense.objects.create(owning_feuser=a, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved={approved_val}, project=g); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=b, "
        f"  share_percent=Decimal('50.0')); "
        f"print(e.pk)"
    )
    if recurring:
        _shell(
            f"from budget.models import Expense, ScheduledExpense; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"e = Expense.objects.get(pk={exp_pk}); "
            f"a = FeUser.objects.get(email='{admin_email}'); "
            f"s = ScheduledExpense.objects.create(owning_feuser=a, title='{title}', "
            f"  type='expense', value=Decimal('50.00'), "
            f"  repeat_every_factor=1, repeat_every_unit='months'); "
            f"e.source_scheduled = s; e.save()"
        )
    return exp_pk


def _create_expense_paid_by_b(admin_email, participant_email, group_id, title, value="30.00"):
    """Create a project expense where B (participant) is the actual payer (dummy pattern not used).
    We instead make user B own the expense and A is a participant.
    """
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending, Project; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"a = FeUser.objects.get(email='{admin_email}'); "
        f"b = FeUser.objects.get(email='{participant_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"e = Expense.objects.create(owning_feuser=b, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved=True, project=g); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=a, "
        f"  share_percent=Decimal('50.0')); "
        f"print(e.pk)"
    )


def _search(driver, query):
    el = driver.find_element(By.ID, "proj-exp-search")
    driver.execute_script(
        "arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
        el, query,
    )
    time.sleep(1)


def _visible_titles(driver):
    return [
        el.text
        for el in driver.find_elements(By.CSS_SELECTOR, ".bexp-title")
    ]


def _nav_to_project(driver, group_id):
    driver.get(_url(f"/projects/{group_id}/"))
    time.sleep(2)


@pytest.fixture(scope="module")
def ctx(driver, w):
    a = setup_user(driver, w, first_name="FilterAdmin", last_name="Alpha")
    b = setup_user(None, None, first_name="FilterMember", last_name="Beta")
    group_id = int(_create_group(a["email"], f"{PREFIX} Project"))
    _add_group_member(group_id, b["email"])

    # Expense A pays: title contains "Groceries"
    e1 = _create_project_expense(a["email"], b["email"], group_id,
                                  f"{PREFIX} Groceries", value="80.00")
    # Expense A pays: title contains "Transport"
    e2 = _create_project_expense(a["email"], b["email"], group_id,
                                  f"{PREFIX} Transport", value="40.00")
    # Expense A pays: recurring (linked to a scheduled expense)
    e3 = _create_project_expense(a["email"], b["email"], group_id,
                                  f"{PREFIX} Recurring Bill", value="20.00", recurring=True)
    # Expense B pays: A is participant
    e4 = _create_expense_paid_by_b(a["email"], b["email"], group_id,
                                    f"{PREFIX} Dinner by B", value="60.00")

    yield {
        "a": a, "b": b,
        "group_id": group_id,
        "e1": e1, "e2": e2, "e3": e3, "e4": e4,
    }
    cleanup_user(a["email"])
    cleanup_user(b["email"])


class TestSearchBar:

    def test_search_shows_matching_expense(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        _nav_to_project(driver, ctx["group_id"])
        _search(driver, f"{PREFIX} Groceries")
        titles = _visible_titles(driver)
        assert any("Groceries" in t for t in titles)
        assert not any("Transport" in t for t in titles)

    def test_search_filters_by_value(self, driver, w, ctx):
        _nav_to_project(driver, ctx["group_id"])
        _search(driver, f"{PREFIX} value<50")
        titles = _visible_titles(driver)
        assert any("Transport" in t for t in titles)  # 40
        assert any("Recurring" in t for t in titles)  # 20
        assert not any("Groceries" in t for t in titles)  # 80

    def test_empty_search_shows_all(self, driver, w, ctx):
        _nav_to_project(driver, ctx["group_id"])
        _search(driver, "")
        titles = _visible_titles(driver)
        assert any("Groceries" in t for t in titles)
        assert any("Transport" in t for t in titles)
        assert any("Recurring" in t for t in titles)
        assert any("Dinner by B" in t for t in titles)

    def test_no_results_shows_empty_message(self, driver, w, ctx):
        _nav_to_project(driver, ctx["group_id"])
        _search(driver, f"{PREFIX} ZZZNoMatchXXX")
        assert "No expenses match" in driver.page_source

    def test_search_does_not_reload_page(self, driver, w, ctx):
        _nav_to_project(driver, ctx["group_id"])
        driver.execute_script("window._pfilt_loaded = true;")
        _search(driver, f"{PREFIX} Groceries")
        still_set = driver.execute_script("return window._pfilt_loaded === true;")
        assert still_set, "Search triggered a full page reload"


class TestHideRecurring:

    def test_hide_recurring_hides_recurring_expense(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        _nav_to_project(driver, ctx["group_id"])
        # Also verify recurring expense is visible before toggling
        assert any("Recurring" in t for t in _visible_titles(driver))
        # Toggle checkbox
        cb = driver.find_element(By.ID, "proj-exp-hide-recurring")
        driver.execute_script("arguments[0].click();", cb)
        time.sleep(1)
        titles = _visible_titles(driver)
        assert not any("Recurring" in t for t in titles)
        assert any("Groceries" in t for t in titles)

    def test_uncheck_hide_recurring_restores_expense(self, driver, w, ctx):
        cb = driver.find_element(By.ID, "proj-exp-hide-recurring")
        driver.execute_script("arguments[0].click();", cb)
        time.sleep(1)
        titles = _visible_titles(driver)
        assert any("Recurring" in t for t in titles)


class TestIPaid:

    def test_i_paid_shows_only_expenses_paid_by_me(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        _nav_to_project(driver, ctx["group_id"])
        cb = driver.find_element(By.ID, "proj-exp-i-paid")
        driver.execute_script("arguments[0].click();", cb)
        time.sleep(1)
        titles = _visible_titles(driver)
        assert any("Groceries" in t for t in titles)
        assert any("Transport" in t for t in titles)
        assert not any("Dinner by B" in t for t in titles)

    def test_i_paid_from_member_perspective(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        _nav_to_project(driver, ctx["group_id"])
        cb = driver.find_element(By.ID, "proj-exp-i-paid")
        driver.execute_script("arguments[0].click();", cb)
        time.sleep(1)
        titles = _visible_titles(driver)
        assert any("Dinner by B" in t for t in titles)
        assert not any("Groceries" in t for t in titles)
        assert not any("Transport" in t for t in titles)

    def test_i_paid_does_not_reload_page(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        _nav_to_project(driver, ctx["group_id"])
        driver.execute_script("window._pfilt_loaded = true;")
        cb = driver.find_element(By.ID, "proj-exp-i-paid")
        driver.execute_script("arguments[0].click();", cb)
        time.sleep(1)
        still_set = driver.execute_script("return window._pfilt_loaded === true;")
        assert still_set, "Filter checkbox triggered a full page reload"


class TestSort:

    def test_sort_by_value_desc_puts_largest_first(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        _nav_to_project(driver, ctx["group_id"])
        sel = driver.find_element(By.ID, "proj-exp-sort-by")
        driver.execute_script(
            "arguments[0].value = 'value';"
            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
            sel,
        )
        time.sleep(1)
        titles = _visible_titles(driver)
        pfilt = [t for t in titles if PREFIX in t]
        assert len(pfilt) >= 2
        # Groceries (80) should appear before Transport (40)
        groceries_idx = next((i for i, t in enumerate(pfilt) if "Groceries" in t), None)
        transport_idx = next((i for i, t in enumerate(pfilt) if "Transport" in t), None)
        assert groceries_idx is not None and transport_idx is not None
        assert groceries_idx < transport_idx

    def test_sort_by_value_asc_puts_smallest_first(self, driver, w, ctx):
        sel_dir = driver.find_element(By.ID, "proj-exp-sort-dir")
        driver.execute_script(
            "arguments[0].value = 'asc';"
            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
            sel_dir,
        )
        time.sleep(1)
        titles = _visible_titles(driver)
        pfilt = [t for t in titles if PREFIX in t]
        transport_idx = next((i for i, t in enumerate(pfilt) if "Transport" in t), None)
        groceries_idx = next((i for i, t in enumerate(pfilt) if "Groceries" in t), None)
        assert transport_idx is not None and groceries_idx is not None
        assert transport_idx < groceries_idx

    def test_sort_does_not_reload_page(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        _nav_to_project(driver, ctx["group_id"])
        driver.execute_script("window._pfilt_loaded = true;")
        sel = driver.find_element(By.ID, "proj-exp-sort-by")
        driver.execute_script(
            "arguments[0].value = 'title';"
            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
            sel,
        )
        time.sleep(1)
        still_set = driver.execute_script("return window._pfilt_loaded === true;")
        assert still_set, "Sort control triggered a full page reload"


class TestCombinedFilters:

    def test_search_and_i_paid_combined(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        _nav_to_project(driver, ctx["group_id"])
        # "Only show what I paid" + search for PREFIX
        cb = driver.find_element(By.ID, "proj-exp-i-paid")
        driver.execute_script("arguments[0].click();", cb)
        time.sleep(0.5)
        _search(driver, f"{PREFIX} Transport")
        titles = _visible_titles(driver)
        assert any("Transport" in t for t in titles)
        assert not any("Groceries" in t for t in titles)
        assert not any("Dinner by B" in t for t in titles)
