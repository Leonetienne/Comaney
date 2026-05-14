"""
Direct settlement to a personal (feuser-owned) dummy buddy is auto-approved immediately.

Requirements: req 14.12 - settling towards an offline personal buddy requires no
creditor confirmation; buddy_approved is set to True at creation time.
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
        assert "Settle Up" in driver.page_source, \
            "Settle Up section must appear when user owes their personal dummy"
        assert "Dusty Dummy" in driver.page_source, \
            "Dummy name must appear in the Settle Up section"

    def test_settle_amount_prefilled(self, driver, w, ctx):
        inp = driver.find_element("css selector", ".settle-amount-input")
        assert inp.get_attribute("value") == "50.00", \
            "Amount input must be pre-filled with 50.00 (the full amount owed)"

    def test_submit_creates_settlement(self, driver, w, ctx):
        driver.find_element(
            "css selector", ".direct-settle-form button[type=submit]"
        ).click()
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

    def test_settle_up_disappears_after_auto_approval(self, driver, w, ctx):
        assert "Settle Up" not in driver.page_source, \
            "Settle Up section must disappear once the dummy settlement is auto-approved"
