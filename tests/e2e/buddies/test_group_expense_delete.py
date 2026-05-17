"""
Group expense delete: owner can delete their own expense; admin can delete a
dummy-owned expense; a non-owner (plain member) cannot delete another
feuser's expense.

Permission matrix from views.py:
  can_delete = is_feuser_direct_owner OR (is_admin AND is_dummy_exp_in_group)
"""
import time

import pytest
import requests as req

from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _create_group, _add_group_member,
)


def _create_approved_group_expense(owner_email: str, participant_email: str,
                                   group_id: int, title: str = "Group Expense",
                                   value: str = "100.00") -> str:
    """Create an approved group expense owned by owner with participant as debtor.
    Returns the expense pk (integer) as string."""
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending, BuddyGroup; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"owner = FeUser.objects.get(email='{owner_email}'); "
        f"part = FeUser.objects.get(email='{participant_email}'); "
        f"g = BuddyGroup.objects.get(pk={group_id}); "
        f"e = Expense.objects.create(owning_feuser=owner, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved=True, buddy_group=g); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=part, "
        f"  share_percent=Decimal('50')); "
        f"print(e.pk)"
    )


def _create_dummy_group_expense(admin_email: str, group_id: int,
                                title: str = "Dummy Expense",
                                value: str = "60.00") -> str:
    """Create an approved group expense where a group dummy is the upfront payer.
    Returns the expense pk (integer) as string."""
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddyGroup, BuddyGroupMember, DummyUser; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"admin = FeUser.objects.get(email='{admin_email}'); "
        f"g = BuddyGroup.objects.get(pk={group_id}); "
        f"d = DummyUser.objects.create(owning_group=g, display_name='Del Dummy'); "
        f"BuddyGroupMember.objects.get_or_create(group=g, dummy=d); "
        f"e = Expense.objects.create(owning_feuser=admin, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved=True, buddy_group=g, "
        f"  is_dummy=True, upfront_payee_dummy=d); "
        f"print(e.pk)"
    )


def _expense_exists(exp_pk: str) -> bool:
    count = _shell(
        f"from budget.models import Expense; "
        f"print(Expense.objects.filter(pk={exp_pk}).count())"
    )
    return count == "1"


# ---------------------------------------------------------------------------
# Expense owner deletes their own group expense
# ---------------------------------------------------------------------------

class TestOwnerDeletesOwnGroupExpense:
    """Expense owner can delete their own approved group expense via the group detail UI."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="DelA", last_name="Owner")
        member = setup_user(None, None, first_name="DelA", last_name="Member")
        group_id = int(_create_group(admin["email"], "OwnerDeleteGroup"))
        _add_group_member(group_id, member["email"])
        exp_pk = _create_approved_group_expense(
            admin["email"], member["email"], group_id,
            title="Owner Deletable Expense",
        )
        yield {"admin": admin, "member": member, "group_id": group_id, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_expense_visible_before_delete(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Owner Deletable Expense" in driver.page_source

    def test_delete_button_visible_for_owner(self, driver, w, ctx):
        delete_forms = driver.find_elements(By.CSS_SELECTOR, "form[action*='/delete/']")
        assert delete_forms, "Owner must see at least one delete button for their own expense"

    def test_owner_deletes_expense_and_flash_shown(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "[id^='btn-delete-']").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "deleted" in driver.page_source.lower(), \
            "Flash message must confirm the expense was deleted"

    def test_expense_gone_from_group_page(self, driver, w, ctx):
        assert "Owner Deletable Expense" not in driver.page_source, \
            "Deleted expense must no longer appear on the group detail page"

    def test_expense_removed_from_database(self, driver, w, ctx):
        assert not _expense_exists(ctx["exp_pk"]), \
            "Deleted expense must not exist in the database"


# ---------------------------------------------------------------------------
# Regular member deletes their own group expense
# ---------------------------------------------------------------------------

class TestMemberDeletesOwnGroupExpense:
    """A non-admin member can delete their own group expense."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="MDelA", last_name="Admin")
        member = setup_user(driver, w, first_name="MDelM", last_name="Member")
        group_id = int(_create_group(admin["email"], "MemberDeleteGroup"))
        _add_group_member(group_id, member["email"])
        exp_pk = _create_approved_group_expense(
            member["email"], admin["email"], group_id,
            title="Member Own Deletable",
        )
        yield {"admin": admin, "member": member, "group_id": group_id, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_member_sees_delete_button_for_own_expense(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Member Own Deletable" in driver.page_source
        delete_forms = driver.find_elements(By.CSS_SELECTOR, "form[action*='/delete/']")
        assert delete_forms, "Member must see delete button for their own group expense"

    def test_member_deletes_own_expense(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "[id^='btn-delete-']").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)

    def test_expense_gone_after_delete(self, driver, w, ctx):
        assert "Member Own Deletable" not in driver.page_source, \
            "Member's deleted expense must not appear on the group page"

    def test_expense_removed_from_database(self, driver, w, ctx):
        assert not _expense_exists(ctx["exp_pk"]), \
            "Member's deleted expense must be gone from the database"


# ---------------------------------------------------------------------------
# Non-owner cannot delete another feuser's group expense
# ---------------------------------------------------------------------------

class TestMemberCannotDeleteOthersGroupExpense:
    """A plain member has no delete button for the admin's expense;
    a direct POST must also be rejected."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="NoDelA", last_name="Admin")
        member = setup_user(driver, w, first_name="NoDelM", last_name="Member")
        group_id = int(_create_group(admin["email"], "NoDeleteGroup"))
        _add_group_member(group_id, member["email"])
        exp_pk = _create_approved_group_expense(
            admin["email"], member["email"], group_id,
            title="Admin Only Expense",
        )
        yield {"admin": admin, "member": member, "group_id": group_id, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_member_sees_no_delete_button_for_admins_expense(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Admin Only Expense" in driver.page_source, \
            "Expense must be visible to the member"
        delete_forms = driver.find_elements(By.CSS_SELECTOR, "form[action*='/delete/']")
        assert not delete_forms, \
            "Member must not see a delete button for the admin's group expense"

    def test_direct_post_does_not_delete_expense(self, driver, w, ctx):
        cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
        csrftoken = cookie_dict.get("csrftoken", "")
        sessionid = cookie_dict.get("sessionid", "")
        req.post(
            _url(f"/buddies/groups/{ctx['group_id']}/expense/{ctx['exp_pk']}/delete/"),
            headers={"X-CSRFToken": csrftoken, "Referer": _url("/buddies/")},
            cookies={"csrftoken": csrftoken, "sessionid": sessionid},
            timeout=10,
            allow_redirects=True,
        )
        assert _expense_exists(ctx["exp_pk"]), \
            "Unauthorized direct POST must not delete the expense from the database"


# ---------------------------------------------------------------------------
# Admin deletes a dummy-owned group expense
# ---------------------------------------------------------------------------

class TestAdminDeletesDummyGroupExpense:
    """Admin can delete a group expense where a group dummy is the upfront payer."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="DumDelA", last_name="Admin")
        group_id = int(_create_group(admin["email"], "DummyDeleteGroup"))
        exp_pk = _create_dummy_group_expense(
            admin["email"], group_id, title="Dummy Payer Expense",
        )
        yield {"admin": admin, "group_id": group_id, "exp_pk": exp_pk}
        cleanup_user(admin["email"])

    def test_dummy_expense_visible_on_group_page(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Dummy Payer Expense" in driver.page_source

    def test_admin_sees_delete_button_for_dummy_expense(self, driver, w, ctx):
        delete_forms = driver.find_elements(By.CSS_SELECTOR, "form[action*='/delete/']")
        assert delete_forms, "Admin must see a delete button for the dummy member's expense"

    def test_admin_deletes_dummy_expense(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "[id^='btn-delete-']").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "deleted" in driver.page_source.lower(), \
            "Flash must confirm deletion"

    def test_dummy_expense_gone_from_group_page(self, driver, w, ctx):
        assert "Dummy Payer Expense" not in driver.page_source, \
            "Admin-deleted dummy expense must no longer appear on the group detail page"

    def test_dummy_expense_removed_from_database(self, driver, w, ctx):
        assert not _expense_exists(ctx["exp_pk"]), \
            "Admin-deleted dummy expense must be gone from the database"
