"""
Group admin can edit a dummy-upfront group expense.

A regular (non-admin) member cannot access the edit form for a dummy-upfront
expense they do not own.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, api_get
from bhelpers import _shell, _login_as, _create_group, _add_group_member


def _create_dummy_upfront_expense(owner_email: str, group_id: int,
                                   dummy_id: int,
                                   title: str = "Dummy Paid Expense",
                                   value: str = "90.00") -> str:
    """Create a group expense where a dummy is the upfront payer.
    Returns the expense pk as string."""
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending, BuddyGroup; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"owner = FeUser.objects.get(email='{owner_email}'); "
        f"g = BuddyGroup.objects.get(pk={group_id}); "
        f"e = Expense.objects.create(owning_feuser=owner, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  is_dummy=True, upfront_payee_dummy_id={dummy_id}, "
        f"  buddy_approved=True, buddy_group=g); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=owner, "
        f"  share_percent=Decimal('100')); "
        f"print(e.pk)"
    )


class TestAdminCanEditDummyUpfrontExpense:
    """Admin sees Edit button and can submit changes for a dummy-upfront group expense."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Ada", last_name="Admin")
        member = setup_user(driver, w, first_name="Mel", last_name="Member")
        group_id = int(_create_group(admin["email"], "Edit Test Group"))
        _add_group_member(group_id, member["email"])
        dummy_id = int(_shell(
            f"from buddies.models import DummyUser, BuddyGroup, BuddyGroupMember; "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Offline Dan'); "
            f"BuddyGroupMember.objects.create(group=g, dummy=d); "
            f"print(d.pk)"
        ))
        expense_pk = int(_create_dummy_upfront_expense(
            admin["email"], group_id, dummy_id,
            title="Dan Paid Camping", value="120.00",
        ))
        admin["group_id"] = group_id
        admin["dummy_id"] = dummy_id
        admin["expense_pk"] = expense_pk
        admin["member"] = member
        yield admin
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_edit_button_visible_for_admin(self, driver, w, ctx):
        _login_as(driver, ctx)
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        links = driver.find_elements(By.CSS_SELECTOR, "a.btn-secondary")
        edit_links = [l for l in links if "edit" in l.get_attribute("href")]
        assert edit_links, "Admin should see an Edit button for the dummy-upfront expense"

    def test_edit_form_loads_for_admin(self, driver, w, ctx):
        expense_pk = ctx["expense_pk"]
        driver.get(_url(f"/budget/expenses/{expense_pk}/edit/"))
        time.sleep(1)
        assert "/edit/" in driver.current_url, "Admin should be able to load the edit form"
        assert "Dan Paid Camping" in driver.page_source

    def test_admin_can_save_title_change(self, driver, w, ctx):
        title_input = driver.find_element(By.CSS_SELECTOR, "input[name='title']")
        title_input.clear()
        title_input.send_keys("Dan Paid Camping Trip")
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(1)
        expense_pk = ctx["expense_pk"]
        resp = api_get(ctx, f"/api/expenses/{expense_pk}/")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Dan Paid Camping Trip"

    def test_edit_button_not_visible_for_non_admin_member(self, driver, w, ctx):
        member = ctx["member"]
        _login_as(driver, member)
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        links = driver.find_elements(By.CSS_SELECTOR, "a.btn-secondary")
        edit_links = [
            l for l in links
            if "edit" in (l.get_attribute("href") or "")
            and str(ctx["expense_pk"]) in (l.get_attribute("href") or "")
        ]
        assert not edit_links, "Non-admin member must not see Edit for a dummy-upfront expense they do not own"

    def test_non_admin_member_cannot_access_edit_form(self, driver, w, ctx):
        expense_pk = ctx["expense_pk"]
        driver.get(_url(f"/budget/expenses/{expense_pk}/edit/"))
        time.sleep(1)
        assert "/edit/" not in driver.current_url, "Non-admin must not access the edit form for another user's dummy-upfront expense"
