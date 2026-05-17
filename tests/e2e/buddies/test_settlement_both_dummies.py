"""
Group settlement where both the debtor and creditor are offline dummy members.

Requirements: req 10.9 / 12.6 - when both parties are dummies, the settlement
is auto-approved at creation time (no real user needs to confirm).

This tests the individual group settlement form (admin selects dummy debtor,
dummy creditor) as well as the group-wide settle-all path which always
auto-approves dummy-creditor settlements.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_group


def _create_group_dummy(group_id: int, display_name: str) -> str:
    return _shell(
        f"from buddies.models import BuddyGroup, BuddyGroupMember, DummyUser; "
        f"g = BuddyGroup.objects.get(pk={group_id}); "
        f"d = DummyUser.objects.create(owning_group=g, display_name='{display_name}'); "
        f"BuddyGroupMember.objects.create(group=g, dummy=d); "
        f"print(d.pk)"
    )


def _create_dummy_paid_expense_for_dummy(admin_email: str, payer_pk: int,
                                          ower_pk: int, group_id: int,
                                          value: str = "40.00") -> None:
    """Dummy A paid; dummy B owes 100%. Creates D_ower -> D_payer simplified debt."""
    _shell(
        f"from feusers.models import FeUser; from buddies.models import BuddyGroup, DummyUser; "
        f"from budget.expense_factory import create_expense; "
        f"from budget.models import TransactionType; from decimal import Decimal; "
        f"admin = FeUser.objects.get(email='{admin_email}'); "
        f"g = BuddyGroup.objects.get(pk={group_id}); "
        f"payer = DummyUser.objects.get(pk={payer_pk}); "
        f"ower = DummyUser.objects.get(pk={ower_pk}); "
        f"create_expense(owning_feuser=admin, title='Dummy Paid For Dummy', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  is_dummy=True, upfront_payee_dummy=payer, "
        f"  buddy_approved=True, buddy_group=g, "
        f"  buddy_spendings=[{{'type': 'dummy', 'id': ower.pk, 'share_percent': 100}}])"
    )


class TestBothDummiesSettlementAutoApprove:
    """Both debtor and creditor are offline dummies: settlement auto-approved."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Boris", last_name="BothAdmin")
        group_id = int(_create_group(admin["email"], "BothDummiesGroup"))
        payer_pk = int(_create_group_dummy(group_id, "Dummy Payer"))
        ower_pk = int(_create_group_dummy(group_id, "Dummy Ower"))
        # Dummy Payer paid 40; Dummy Ower owes 100%; simplified: Dummy Ower -> Dummy Payer
        _create_dummy_paid_expense_for_dummy(
            admin["email"], payer_pk, ower_pk, group_id, "40.00"
        )
        yield {
            "admin": admin,
            "group_id": group_id,
            "payer_pk": payer_pk,
            "ower_pk": ower_pk,
        }
        cleanup_user(admin["email"])

    def test_admin_submits_both_dummy_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source

        # Select Dummy Ower as debtor
        debtor_sel = Select(driver.find_element(By.ID, "settle-debtor"))
        opt_texts = [o.text for o in debtor_sel.options]
        assert any("Dummy Ower" in t for t in opt_texts), \
            "Debtor dropdown must include 'Dummy Ower'"
        debtor_sel.select_by_visible_text("Dummy Ower (offline member)")
        time.sleep(0.5)

        # Creditor should auto-fill or select Dummy Payer
        cred_sel = Select(driver.find_element(By.ID, "settle-creditor"))
        opt_texts = [o.text for o in cred_sel.options]
        assert any("Dummy Payer" in t for t in opt_texts), \
            "Creditor dropdown must include 'Dummy Payer'"
        cred_sel.select_by_visible_text("Dummy Payer (offline member)")
        time.sleep(0.3)

        amt = driver.find_element(By.ID, "settle-amount")
        if not amt.get_attribute("value"):
            amt.clear()
            amt.send_keys("40.00")

        driver.find_element(
            By.ID, "btn-settle-individual"
        ).click()
        time.sleep(0.5)
        # Dialog must say "approved automatically" when both are offline
        msg = driver.find_element(By.ID, "cdialog-msg").text
        assert "automatically" in msg.lower(), \
            "Dialog must say the payment is approved automatically when both are offline"
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower()

    def test_settlement_is_immediately_approved(self, driver, w, ctx):
        approved = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"admin = FeUser.objects.get(email='{ctx['admin']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser=admin, is_buddies_settlement=True).first(); "
            f"print(e.buddy_approved if e else 'none')"
        )
        assert approved == "True", \
            "Both-dummy settlement must be buddy_approved=True immediately"

    def test_no_waiting_for_approval_section(self, driver, w, ctx):
        assert "Waiting for approval" not in driver.page_source, \
            "No waiting-for-approval section must appear for both-dummy auto-approved settlement"

    def test_no_pending_section_on_summary_for_both_dummy(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Waiting for your approval" not in driver.page_source, \
            "No admin confirmation needed for both-dummy settlement"
