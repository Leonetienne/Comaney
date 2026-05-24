"""
Verify the confirm-settlement page shows the right creditor wording.

- Real user creditor: heading says "Did you" (settling against yourself).
- Offline-member creditor: heading says "Did Rainer (offline member)".
"""
import time

import pytest

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_group


def _create_settlement_to_feuser(debtor_email: str, creditor_email: str) -> str:
    """Create a pending settlement expense; return pk."""
    return _shell(
        f"from budget.expense_factory import create_expense; "
        f"from budget.models import TransactionType; "
        f"from feusers.models import FeUser; "
        f"from datetime import date; from decimal import Decimal; "
        f"debtor = FeUser.objects.get(email='{debtor_email}'); "
        f"creditor = FeUser.objects.get(email='{creditor_email}'); "
        f"e = create_expense(owning_feuser=debtor, title='Test settlement', "
        f"  type=TransactionType.EXPENSE, value=Decimal('10.00'), "
        f"  date_due=date.today(), settled=True, notify=False, "
        f"  is_buddies_settlement=True, buddy_approved=False, "
        f"  buddy_spendings=[{{'type':'feuser','id':creditor.pk,'share_percent':Decimal('100')}}]); "
        f"print(e.pk)"
    )


def _create_group_dummy_settlement(group_id: int, dummy_name: str,
                                   debtor_email: str) -> tuple[str, str]:
    """Create dummy + pending settlement where dummy is creditor; return (dummy_pk, expense_pk)."""
    dummy_pk = _shell(
        f"from buddies.models import Project, BuddyGroupMember, DummyUser; "
        f"g = Project.objects.get(pk={group_id}); "
        f"d = DummyUser.objects.create(owning_group=g, display_name='{dummy_name}'); "
        f"BuddyGroupMember.objects.create(group=g, dummy=d); "
        f"print(d.pk)"
    )
    expense_pk = _shell(
        f"from budget.expense_factory import create_expense; "
        f"from budget.models import TransactionType; "
        f"from buddies.models import Project; "
        f"from feusers.models import FeUser; "
        f"from datetime import date; from decimal import Decimal; "
        f"debtor = FeUser.objects.get(email='{debtor_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"e = create_expense(owning_feuser=debtor, title='Test dummy settlement', "
        f"  type=TransactionType.EXPENSE, value=Decimal('10.00'), "
        f"  date_due=date.today(), settled=True, notify=False, "
        f"  is_buddies_settlement=True, buddy_approved=False, project=g, "
        f"  buddy_spendings=[{{'type':'dummy','id':{dummy_pk},'share_percent':Decimal('100')}}]); "
        f"print(e.pk)"
    )
    return dummy_pk, expense_pk


class TestConfirmSettlementHeadingRealUser:
    """Confirm page for a real-user creditor says 'Did you'."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        debtor = setup_user(None, None, first_name="Dana", last_name="Debtor")
        creditor = setup_user(driver, w, first_name="Cora", last_name="Creditor")
        expense_pk = _create_settlement_to_feuser(debtor["email"], creditor["email"])
        yield {"creditor": creditor, "expense_pk": expense_pk}
        cleanup_user(debtor["email"])
        cleanup_user(creditor["email"])

    def test_confirm_page_says_did_you(self, driver, w, ctx):
        _login_as(driver, ctx["creditor"])
        driver.get(_url(f"/buddies/expense/{ctx['expense_pk']}/approve-settlement/"))
        time.sleep(1)
        assert "Did you" in driver.page_source, \
            "Confirm page for real-user creditor must say 'Did you'"
        assert "Did Rainer" not in driver.page_source, \
            "Real-user confirm page must not mention an offline member name"


class TestConfirmSettlementHeadingOfflineMember:
    """Confirm page for an offline-member creditor says 'Did Rainer (offline member)'."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Anna", last_name="AdminHead")
        group_id = int(_create_group(admin["email"], "RainerHeadingGroup"))
        _, expense_pk = _create_group_dummy_settlement(
            group_id, "Rainer", admin["email"]
        )
        yield {"admin": admin, "group_id": group_id, "expense_pk": expense_pk}
        cleanup_user(admin["email"])

    def test_confirm_page_says_did_rainer(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(
            f"/projects/{ctx['group_id']}/expense/{ctx['expense_pk']}/approve-dummy/"
        ))
        time.sleep(1)
        assert "Did Rainer (offline member)" in driver.page_source, \
            "Confirm page for offline-member creditor must say 'Did Rainer (offline member)'"
        assert "Did you" not in driver.page_source, \
            "Offline-member confirm page must not say 'Did you'"
