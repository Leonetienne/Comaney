"""
Direct settlement with personal (feuser-owned) dummy buddies.

Covers:
  - Feuser owes dummy: settling is auto-approved immediately (req 14.12)
  - Dummy owes feuser: "who pays" dropdown appears, recording dummy-pays-feuser settlement
    is auto-approved and clears the debt
"""
import time

import pytest

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as


def _create_personal_dummy(owner_email: str, display_name: str) -> str:
    """Create a personal (feuser-owned) DummyUser; return pk as string."""
    return _shell(
        f"from feusers.models import FeUser; from buddies.models import DummyUser; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"d = DummyUser.objects.create(owning_feuser=u, display_name='{display_name}'); "
        f"print(d.pk)"
    )


def _create_dummy_paid_expense(owner_email: str, dummy_pk: int, value: str = "50.00") -> None:
    """
    Create an approved expense where the personal dummy paid upfront and the
    expense owner (feuser) owes the full amount (implicit share = 100%).
    """
    _shell(
        f"from feusers.models import FeUser; from buddies.models import DummyUser; "
        f"from budget.expense_factory import create_expense; "
        f"from budget.models import TransactionType; from decimal import Decimal; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"d = DummyUser.objects.get(pk={dummy_pk}); "
        f"create_expense(owning_feuser=u, title='Dummy Paid Upfront', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  is_dummy=True, upfront_payee_dummy=d, "
        f"  buddy_approved=True, buddy_spendings=[])"
    )


class TestDirectSettlementToPersonalDummy:
    """A owes their personal dummy; settling is auto-approved with no confirmation step."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Dora", last_name="DummyOwner")
        dummy_pk = int(_create_personal_dummy(a["email"], "Dusty Dummy"))
        # Dummy paid 50; A owes 100% (implicit share = 50.00)
        _create_dummy_paid_expense(a["email"], dummy_pk, value="50.00")
        yield {"a": a, "dummy_pk": dummy_pk}
        cleanup_user(a["email"])

    def test_settle_up_section_shows_dummy(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source, \
            "Settle Up section must appear when user owes their personal dummy"
        assert "Dusty Dummy" in driver.page_source, \
            "Dummy name must appear in the Settle Up section"

    def test_settle_amount_prefilled(self, driver, w, ctx):
        inp = driver.find_element("id", "direct-settle-amount")
        assert inp.get_attribute("value") == "50.00", \
            "Amount input must be pre-filled with 50.00 (the full amount owed)"

    def test_submit_creates_settlement(self, driver, w, ctx):
        driver.find_element("id", "btn-direct-settle").click()
        time.sleep(0.5)
        driver.find_element("id", "cdialog-ok").click()
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower(), \
            "Flash must confirm that a settlement record was created"

    def test_settlement_is_immediately_approved(self, driver, w, ctx):
        approved = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser=a, is_buddies_settlement=True).first(); "
            f"print(e.buddy_approved if e else 'none')"
        )
        assert approved == "True", \
            "Settlement to personal dummy must be buddy_approved=True immediately"

    def test_no_pending_settlement_receipts_section(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Pending settlement receipts" not in driver.page_source, \
            "No creditor confirmation is needed; pending section must not appear"

    def test_amount_cleared_after_settlement(self, driver, w, ctx):
        # Debt is cleared; amount input must no longer be pre-filled
        inp = driver.find_element("id", "direct-settle-amount")
        val = inp.get_attribute("value")
        assert val in ("", None), \
            f"Amount input must be empty after dummy settlement is approved, got '{val}'"


def _create_feuser_paid_expense(owner_email: str, dummy_pk: int, value: str = "60.00") -> None:
    """
    Create an approved expense where the feuser paid and the dummy owes the full amount
    (dummy is participant at 100%).  Feuser's net vs dummy is positive (dummy owes feuser).
    """
    _shell(
        f"from feusers.models import FeUser; from buddies.models import DummyUser; "
        f"from budget.expense_factory import create_expense; "
        f"from budget.models import TransactionType; from decimal import Decimal; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"d = DummyUser.objects.get(pk={dummy_pk}); "
        f"create_expense(owning_feuser=u, title='Feuser Paid For Dummy', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  buddy_approved=True, "
        f"  buddy_spendings=[{{'type': 'dummy', 'id': d.pk, 'share_percent': 100}}])"
    )


class TestDirectSettlementFromDummy:
    """
    Personal offline buddy owes feuser: 'who pays' dropdown appears with the dummy
    listed, and recording a dummy-pays-feuser settlement is auto-approved and clears
    the debt.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Faye", last_name="OwedBy")
        dummy_pk = int(_create_personal_dummy(a["email"], "Owing Offline"))
        # A paid 60; dummy owes 100% (net = +60 for A)
        _create_feuser_paid_expense(a["email"], dummy_pk, value="60.00")
        yield {"a": a, "dummy_pk": dummy_pk}
        cleanup_user(a["email"])

    def test_who_pays_dropdown_visible(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        row = driver.find_element("id", "direct-settle-debtor-row")
        assert row.is_displayed(), \
            "Who's paying row must be visible when user has personal offline buddies"

    def test_who_pays_contains_offline_buddy(self, driver, w, ctx):
        assert "Owing Offline" in driver.page_source, \
            "Offline buddy must appear in the page (in JSON or dropdown)"

    def test_selecting_dummy_as_debtor_locks_pay_to_you(self, driver, w, ctx):
        from selenium.webdriver.support.ui import Select
        debtor_sel = Select(driver.find_element("id", "direct-settle-debtor-select"))
        debtor_sel.select_by_visible_text("Owing Offline (offline member)")
        time.sleep(0.3)
        creditor_sel = Select(driver.find_element("id", "direct-settle-creditor"))
        options = [o.text for o in creditor_sel.options]
        assert options == ["You"], \
            f"When offline buddy is debtor, Pay to must only offer 'You', got {options}"

    def test_amount_prefilled_with_debt_owed_to_feuser(self, driver, w, ctx):
        inp = driver.find_element("id", "direct-settle-amount")
        assert inp.get_attribute("value") == "60.00", \
            "Amount must be pre-filled with 60.00 (what the dummy owes feuser)"

    def test_confirm_dialog_mentions_auto_approve(self, driver, w, ctx):
        driver.find_element("id", "btn-direct-settle").click()
        time.sleep(0.5)
        msg = driver.find_element("id", "cdialog-msg").text
        assert "Owing Offline" in msg, \
            "Dialog must name the offline buddy as the payer"
        assert "automatically" in msg.lower(), \
            "Dialog must say the settlement will be approved automatically"
        driver.find_element("id", "cdialog-cancel").click()
        time.sleep(0.3)

    def test_submit_creates_settlement_record(self, driver, w, ctx):
        driver.find_element("id", "btn-direct-settle").click()
        driver.find_element("id", "cdialog-ok").click()
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower(), \
            "Flash must confirm settlement was created"

    def test_settlement_is_auto_approved(self, driver, w, ctx):
        approved = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser=a, is_buddies_settlement=True, "
            f"  is_dummy=True).first(); "
            f"print(e.buddy_approved if e else 'none')"
        )
        assert approved == "True", \
            "Dummy-pays-feuser settlement must be buddy_approved=True immediately"

    def test_debt_cleared_after_settlement(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        # After settlement, pre-fill should be empty (no more debt)
        inp = driver.find_element("id", "direct-settle-amount")
        val = inp.get_attribute("value")
        assert val in ("", None), \
            f"Amount must not be pre-filled after debt is cleared, got '{val}'"
