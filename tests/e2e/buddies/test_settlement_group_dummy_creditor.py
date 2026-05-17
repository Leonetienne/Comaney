"""
Group settlement where a group dummy is the creditor (recipient of payment).

Two sub-scenarios:

1. Non-admin member B settles toward dummy D:
   - Settlement created with buddy_approved=False.
   - Admin A sees it in "Waiting for your approval" on /buddies/summary/.
   - Admin A approves it via the Review button.

2. Admin A settles toward dummy D (auto-approve fix):
   - With the code fix in create_individual_group_settlement, when admin is
     the debtor and the creditor is a dummy, the settlement is auto-approved.
   - buddy_approved=True immediately; no admin confirmation step needed.

Requirements: req 10.8 and the admin-auto-approve code fix.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_group, _add_group_member


def _create_group_dummy(group_id: int, display_name: str) -> str:
    return _shell(
        f"from buddies.models import BuddyGroup, BuddyGroupMember, DummyUser; "
        f"g = BuddyGroup.objects.get(pk={group_id}); "
        f"d = DummyUser.objects.create(owning_group=g, display_name='{display_name}'); "
        f"BuddyGroupMember.objects.create(group=g, dummy=d); "
        f"print(d.pk)"
    )


class TestGroupSettlementNonAdminPaysDummy:
    """Non-admin B pays dummy D; admin A must confirm via buddy summary page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Alma", last_name="GroupAdmin2")
        member = setup_user(driver, w, first_name="Bruno", last_name="GroupMember")
        group_id = int(_create_group(admin["email"], "DummyCreditGroup"))
        _add_group_member(group_id, member["email"])
        dummy_pk = int(_create_group_dummy(group_id, "Cash Dummy"))
        yield {
            "admin": admin,
            "member": member,
            "group_id": group_id,
            "dummy_pk": dummy_pk,
        }
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_member_submits_payment_to_dummy(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source, \
            "Pay someone back section must be visible for member"

        # Select dummy as creditor; no amount pre-fill expected (no prior expense),
        # so enter manually
        from selenium.webdriver.support.ui import Select
        cred_sel = Select(driver.find_element(By.ID, "settle-creditor"))
        opt_texts = [o.text for o in cred_sel.options]
        assert any("Cash Dummy" in t for t in opt_texts), \
            "Creditor dropdown must include the group dummy"
        cred_sel.select_by_visible_text("Cash Dummy (offline member)")
        time.sleep(0.3)

        amt = driver.find_element(By.ID, "settle-amount")
        amt.clear()
        amt.send_keys("25.00")

        driver.find_element(
            By.ID, "btn-settle-individual"
        ).click()
        time.sleep(0.5)
        # Dialog must say admin needs to confirm
        msg = driver.find_element(By.ID, "cdialog-msg").text
        assert "admin" in msg.lower() or "offline" in msg.lower(), \
            "Dialog must mention that the admin needs to confirm on buddy summary"
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower(), \
            "Flash must confirm settlement was created"

    def test_settlement_starts_not_approved(self, driver, w, ctx):
        count = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['member']['email']}'); "
            f"print(Expense.objects.filter(owning_feuser=b, is_buddies_settlement=True, "
            f"  buddy_approved=False).count())"
        )
        assert count == "1", \
            "Non-admin settlement to dummy must start with buddy_approved=False"

    def test_admin_sees_pending_approvals_section(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Waiting for your approval" in driver.page_source, \
            "Admin must see 'Waiting for your approval' section"
        assert "Cash Dummy" in driver.page_source, \
            "Dummy name must appear in the pending section"

    def test_admin_approves_dummy_settlement(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "[id^='btn-review-dummy-']").click()
        time.sleep(1)
        driver.find_element(By.ID, "btn-approve-settlement").click()
        time.sleep(1)
        assert "confirmed" in driver.page_source.lower() or \
               "approved" in driver.page_source.lower(), \
            "Flash must confirm approval on behalf of the offline member"

    def test_section_gone_after_approval(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Waiting for your approval" not in driver.page_source, \
            "Section must disappear after admin has approved"

    def test_settlement_is_now_approved(self, driver, w, ctx):
        count = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['member']['email']}'); "
            f"print(Expense.objects.filter(owning_feuser=b, is_buddies_settlement=True, "
            f"  buddy_approved=True).count())"
        )
        assert count == "1", \
            "Settlement must be buddy_approved=True after admin approves"


class TestGroupSettlementAdminPaysDummyAutoApprove:
    """Admin A settles toward dummy D: auto-approved immediately (no confirmation step)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Ada", last_name="AutoAdmin")
        group_id = int(_create_group(admin["email"], "AdminAutoApproveGroup"))
        dummy_pk = int(_create_group_dummy(group_id, "Instant Dummy"))
        yield {"admin": admin, "group_id": group_id, "dummy_pk": dummy_pk}
        cleanup_user(admin["email"])

    def test_admin_submits_payment_to_dummy(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source

        # Admin selects self as debtor (default), dummy as creditor
        from selenium.webdriver.support.ui import Select
        cred_sel = Select(driver.find_element(By.ID, "settle-creditor"))
        opt_texts = [o.text for o in cred_sel.options]
        assert any("Instant Dummy" in t for t in opt_texts), \
            "Creditor dropdown must include the group dummy"
        cred_sel.select_by_visible_text("Instant Dummy (offline member)")
        time.sleep(0.3)

        amt = driver.find_element(By.ID, "settle-amount")
        amt.clear()
        amt.send_keys("15.00")

        driver.find_element(
            By.ID, "btn-settle-individual"
        ).click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower()

    def test_settlement_is_immediately_approved(self, driver, w, ctx):
        approved = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['admin']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser=a, is_buddies_settlement=True).first(); "
            f"print(e.buddy_approved if e else 'none')"
        )
        assert approved == "True", \
            "Admin settling to dummy creditor must be auto-approved (buddy_approved=True)"

    def test_no_pending_section_for_admin_after_auto_approve(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Waiting for your approval" not in driver.page_source, \
            "Auto-approved settlement must not create a pending item"
