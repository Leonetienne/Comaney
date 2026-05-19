"""
Group expense unlink: removes an expense from the group breakdown while
keeping it in the owner's personal expense list.

Permission: is_feuser_direct_owner OR is_admin.
When an admin unlinks another member's expense, an email is sent to the
expense owner and to any feuser participants.

After unlink the expense has:
  - buddy_group = None
  - buddy_spendings deleted
  - buddy_approved = True
  - is_dummy = False
"""
import time

import pytest
import requests as req

from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, fetch_email, mailpit_seen_ids
from bhelpers import (
    _shell, _login_as, _create_group, _add_group_member,
)


def _create_approved_group_expense(owner_email: str, participant_email: str,
                                   group_id: int, title: str = "Group Expense",
                                   value: str = "100.00") -> str:
    """Create an approved group expense; return expense pk as string."""
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import Project, BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"import datetime; "
        f"owner = FeUser.objects.get(email='{owner_email}'); "
        f"part = FeUser.objects.get(email='{participant_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"e = Expense.objects.create(owning_feuser=owner, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  date_due=datetime.date.today(), "
        f"  buddy_approved=True, project=g); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=part, "
        f"  share_percent=Decimal('50')); "
        f"print(e.pk)"
    )


def _expense_in_group(exp_pk: str, group_id: int) -> bool:
    """Return True if the expense still belongs to the given group."""
    result = _shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.filter(pk={exp_pk}).first(); "
        f"print(e.project_id if e else 'none')"
    )
    return result == str(group_id)


def _expense_buddy_spendings_count(exp_pk: str) -> int:
    return int(_shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.filter(pk={exp_pk}).first(); "
        f"print(e.buddy_spendings.count() if e else -1)"
    ))


# ---------------------------------------------------------------------------
# Owner unlinks their own expense
# ---------------------------------------------------------------------------

class TestOwnerUnlinksOwnExpense:
    """Expense owner uses the Unlink button; the expense disappears from the group
    but stays in their personal expense list."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="UnlA", last_name="Owner")
        member = setup_user(None, None, first_name="UnlA", last_name="Member")
        group_id = int(_create_group(admin["email"], "UnlinkOwnerGroup"))
        _add_group_member(group_id, member["email"])
        exp_pk = _create_approved_group_expense(
            admin["email"], member["email"], group_id,
            title="Owner Unlink Expense",
        )
        yield {"admin": admin, "member": member, "group_id": group_id, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_expense_visible_on_group_page(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Owner Unlink Expense" in driver.page_source

    def test_unlink_button_visible_for_owner(self, driver, w, ctx):
        unlink_forms = driver.find_elements(By.CSS_SELECTOR, "form[action*='/unlink/']")
        assert unlink_forms, "Owner must see an Unlink button for their own group expense"

    def test_owner_unlinks_expense_and_flash_shown(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "[id^='btn-unlink-']").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "unlinked" in driver.page_source.lower(), \
            "Flash message must confirm the expense was unlinked"

    def test_expense_gone_from_group_page(self, driver, w, ctx):
        assert "Owner Unlink Expense" not in driver.page_source, \
            "Unlinked expense must not appear on the group detail page"

    def test_expense_no_longer_in_group_in_db(self, driver, w, ctx):
        assert not _expense_in_group(ctx["exp_pk"], ctx["group_id"]), \
            "Expense must have buddy_group=None after unlink"

    def test_expense_still_in_owners_api_list(self, driver, w, ctx):
        api_key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{ctx['admin']['email']}').api_key)"
        )
        resp = req.get(
            _url("/api/v1/expenses/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        assert resp.status_code == 200
        titles = [e["title"] for e in resp.json()["expenses"]]
        assert any("Owner Unlink Expense" in t for t in titles), \
            "Unlinked expense must still appear in the owner's personal expense list"

    def test_expense_buddy_spendings_cleared(self, driver, w, ctx):
        count = _expense_buddy_spendings_count(ctx["exp_pk"])
        assert count == 0, \
            "Unlinked expense must have no BuddySpending rows"


# ---------------------------------------------------------------------------
# Admin unlinks another member's expense; email sent to owner
# ---------------------------------------------------------------------------

class TestAdminUnlinksMemberExpense:
    """Admin unlinks a member's expense; the member (expense owner) receives an email
    and the expense remains in the member's personal expense list."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="UnlAdmin", last_name="Admin")
        member = setup_user(None, None, first_name="UnlMember", last_name="Member")
        group_id = int(_create_group(admin["email"], "AdminUnlinkGroup"))
        _add_group_member(group_id, member["email"])
        # Expense owned by the member (not the admin)
        exp_pk = _create_approved_group_expense(
            member["email"], admin["email"], group_id,
            title="Member Expense To Unlink",
        )
        yield {"admin": admin, "member": member, "group_id": group_id, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_admin_sees_unlink_button_for_members_expense(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Member Expense To Unlink" in driver.page_source
        unlink_forms = driver.find_elements(By.CSS_SELECTOR, "form[action*='/unlink/']")
        assert unlink_forms, "Admin must see an Unlink button even for another member's expense"

    def test_admin_unlinks_members_expense(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        driver.find_element(By.CSS_SELECTOR, "[id^='btn-unlink-']").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "unlinked" in driver.page_source.lower(), \
            "Flash message must confirm the expense was unlinked"

    def test_expense_gone_from_group_page(self, driver, w, ctx):
        assert "Member Expense To Unlink" not in driver.page_source, \
            "Unlinked expense must not appear on the group detail page"

    def test_expense_owner_receives_notification_email(self, driver, w, ctx):
        body = fetch_email(
            ctx["member"]["email"],
            subject_fragment="unlinked",
            timeout=30,
            ignore_ids=ctx.get("seen_before"),
        )
        assert body, \
            "Expense owner must receive an email when admin unlinks their expense"
        assert "UnlAdmin" in body or "Admin" in body or "group" in body.lower(), \
            "Unlink notification must identify the admin or the group"

    def test_expense_still_in_members_api_list(self, driver, w, ctx):
        api_key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{ctx['member']['email']}').api_key)"
        )
        resp = req.get(
            _url("/api/v1/expenses/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        assert resp.status_code == 200
        titles = [e["title"] for e in resp.json()["expenses"]]
        assert any("Member Expense To Unlink" in t for t in titles), \
            "Unlinked expense must still appear in the member's personal expense list"


# ---------------------------------------------------------------------------
# Non-owner, non-admin cannot unlink another feuser's expense
# ---------------------------------------------------------------------------

class TestNonAdminCannotUnlinkOthersExpense:
    """A plain member has no Unlink button for the admin's expense; direct POST must fail."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="NoUnlAdmin", last_name="Admin")
        member = setup_user(driver, w, first_name="NoUnlMember", last_name="Member")
        group_id = int(_create_group(admin["email"], "NoUnlinkGroup"))
        _add_group_member(group_id, member["email"])
        exp_pk = _create_approved_group_expense(
            admin["email"], member["email"], group_id,
            title="Admin Expense No Unlink",
        )
        yield {"admin": admin, "member": member, "group_id": group_id, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_member_sees_no_unlink_button_for_admins_expense(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Admin Expense No Unlink" in driver.page_source
        # Member owns no expense in this group, so no unlink button should appear
        unlink_forms = driver.find_elements(By.CSS_SELECTOR, "form[action*='/unlink/']")
        assert not unlink_forms, \
            "Member must not see an Unlink button for the admin's expense"

    def test_direct_post_does_not_unlink_expense(self, driver, w, ctx):
        cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
        csrftoken = cookie_dict.get("csrftoken", "")
        sessionid = cookie_dict.get("sessionid", "")
        req.post(
            _url(f"/projects/{ctx['group_id']}/expense/{ctx['exp_pk']}/unlink/"),
            headers={"X-CSRFToken": csrftoken, "Referer": _url("/buddies/")},
            cookies={"csrftoken": csrftoken, "sessionid": sessionid},
            timeout=10,
            allow_redirects=True,
        )
        assert _expense_in_group(ctx["exp_pk"], ctx["group_id"]), \
            "Unauthorized unlink POST must not remove the expense from the group"
