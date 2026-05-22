"""
Verify that BuddySpending share_percent values are preserved correctly when
the upfront payer is changed via BuddyExpenseService.change_upfront_payer().

[S1] feuser -> feuser: old owner's implicit share becomes a spending row at the
     correct value; the new owner loses their spending row; all other
     participants keep their original share_percent unchanged.

[S2] feuser -> dummy: same share invariants for the dummy-payer code path.
"""
import pytest

from helpers import setup_user, cleanup_user
from bhelpers import _shell, _create_buddy_link, _get_pk


def _spending_share(expense_pk: int, email: str) -> float | None:
    """Return share_percent as float for a feuser participant, or None if no row exists."""
    raw = _shell(
        f"from feusers.models import FeUser; from buddies.models import BuddySpending; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"bs = BuddySpending.objects.filter(expense_id={expense_pk}, participant_feuser=u).first(); "
        f"print(str(bs.share_percent) if bs else '')"
    ).strip()
    return float(raw) if raw else None


def _dummy_spending_share(expense_pk: int, dummy_pk: int) -> float | None:
    """Return share_percent as float for a dummy participant, or None if no row exists."""
    raw = _shell(
        f"from buddies.models import BuddySpending; "
        f"bs = BuddySpending.objects.filter(expense_id={expense_pk}, participant_dummy_id={dummy_pk}).first(); "
        f"print(str(bs.share_percent) if bs else '')"
    ).strip()
    return float(raw) if raw else None


# ===========================================================================
# S1: feuser -> feuser payer change
# ===========================================================================

class TestFeuserPayerChangeSharesPreserved:
    """[S1] Shares of uninvolved participants stay intact; old owner gets a spending
    row equal to their former implicit share; new owner has no spending row."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        # old_owner implicit share: 100 - 50 - 20 = 30 %
        old_owner    = setup_user(driver, w, first_name="PayOld", last_name="A")
        new_payer    = setup_user(None, None, first_name="PayNew", last_name="B")
        bystander    = setup_user(None, None, first_name="PayBy",  last_name="C")
        _create_buddy_link(old_owner["email"], new_payer["email"])
        _create_buddy_link(old_owner["email"], bystander["email"])

        new_payer_pk  = int(_get_pk(new_payer["email"]))
        bystander_pk  = int(_get_pk(bystander["email"]))

        exp_pk = int(_shell(
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"from buddies.models import BuddySpending; from decimal import Decimal; "
            f"o = FeUser.objects.get(email='{old_owner['email']}'); "
            f"e = Expense.objects.create(owning_feuser=o, title='S1 Exp', "
            f"  type='expense', value='100.00', settled=False); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={new_payer_pk}, "
            f"  share_percent=Decimal('50')); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={bystander_pk}, "
            f"  share_percent=Decimal('20')); "
            f"print(e.pk)"
        ))

        _shell(
            f"from budget.models import Expense; from feusers.models import FeUser; "
            f"from buddies.services import BuddyExpenseService; "
            f"e = Expense.objects.get(pk={exp_pk}); "
            f"new = FeUser.objects.get(pk={new_payer_pk}); "
            f"BuddyExpenseService.change_upfront_payer(e, new_payer_feuser=new)"
        )

        yield {
            "exp_pk": exp_pk,
            "old_owner": old_owner,
            "new_payer": new_payer,
            "bystander": bystander,
        }
        cleanup_user(old_owner["email"])
        cleanup_user(new_payer["email"])
        cleanup_user(bystander["email"])

    def test_bystander_share_unchanged(self, ctx):
        assert _spending_share(ctx["exp_pk"], ctx["bystander"]["email"]) == 20, \
            "[S1] Bystander share_percent must remain 20 after payer change"

    def test_old_owner_gets_spending_with_correct_share(self, ctx):
        assert _spending_share(ctx["exp_pk"], ctx["old_owner"]["email"]) == 30, \
            "[S1] Old owner must receive a spending row with their former implicit share (30)"

    def test_new_payer_has_no_spending_row(self, ctx):
        assert _spending_share(ctx["exp_pk"], ctx["new_payer"]["email"]) is None, \
            "[S1] New payer must have no spending row (they are now the expense owner)"


# ===========================================================================
# S2: feuser -> dummy payer change
# ===========================================================================

class TestDummyPayerChangeSharesPreserved:
    """[S2] Same share invariants when the new upfront payer is a dummy user."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        # old_owner implicit share: 100 - 60 = 40 %
        old_owner  = setup_user(driver, w, first_name="DPayOld", last_name="A")
        participant = setup_user(None, None, first_name="DPayPar", last_name="B")
        _create_buddy_link(old_owner["email"], participant["email"])

        participant_pk = int(_get_pk(participant["email"]))

        setup = _shell(
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; from decimal import Decimal; "
            f"o = FeUser.objects.get(email='{old_owner['email']}'); "
            f"dummy = DummyUser.objects.create(owning_feuser=o, display_name='DPay Dummy'); "
            f"e = Expense.objects.create(owning_feuser=o, title='S2 Exp', "
            f"  type='expense', value='100.00', settled=False); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={participant_pk}, "
            f"  share_percent=Decimal('60')); "
            f"print(e.pk, dummy.pk)"
        )
        exp_pk, dummy_pk = [int(x) for x in setup.split()]

        _shell(
            f"from budget.models import Expense; from buddies.models import DummyUser; "
            f"from buddies.services import BuddyExpenseService; "
            f"e = Expense.objects.get(pk={exp_pk}); "
            f"d = DummyUser.objects.get(pk={dummy_pk}); "
            f"BuddyExpenseService.change_upfront_payer(e, new_payer_dummy=d)"
        )

        yield {
            "exp_pk": exp_pk,
            "dummy_pk": dummy_pk,
            "old_owner": old_owner,
            "participant": participant,
        }
        cleanup_user(old_owner["email"])
        cleanup_user(participant["email"])

    def test_participant_share_unchanged(self, ctx):
        assert _spending_share(ctx["exp_pk"], ctx["participant"]["email"]) == 60, \
            "[S2] Participant share_percent must remain 60 after dummy-payer change"

    def test_old_owner_gets_spending_with_correct_share(self, ctx):
        assert _spending_share(ctx["exp_pk"], ctx["old_owner"]["email"]) == 40, \
            "[S2] Old owner must receive a spending row with their former implicit share (40)"

    def test_dummy_has_no_spending_row(self, ctx):
        assert _dummy_spending_share(ctx["exp_pk"], ctx["dummy_pk"]) is None, \
            "[S2] New dummy payer must have no spending row (they are the upfront payer)"
