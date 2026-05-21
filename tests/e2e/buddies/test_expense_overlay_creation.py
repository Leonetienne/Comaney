"""
Tests for overlay auto-creation logic triggered by expense creation and
upfront-payer transfers.

[C1] Creating expense with another feuser as upfront payer:
     - expense category/tags are reconciled to the owning feuser's objects by title
     - overlay for creating feuser is auto-created with their original selection
     - no overlay when creating feuser had no matching category/tags

[C2] Creating feuser's overlay contains exactly what was in the form (original
     selection), even when the owning feuser has no matching equivalent.

[C3] Auto-overlay for other real-user participants on expense creation:
     - participants with title-matching category/tags get overlays
     - participants with no matches do not get overlays

[C4] Changing upfront payer (feuser A -> feuser B):
     - old owner (A) gets overlay snapshotted from current expense tags/category
     - new owner (B) has an existing overlay: it is applied to expense, overlay deleted
     - new owner (B) has no overlay: title-matching is used instead

[C5] No snapshot overlay for old owner if expense had no category/tags.
"""
import time

import pytest

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk,
    _create_group, _add_group_member,
)


# ---------------------------------------------------------------------------
# Shared shell helpers
# ---------------------------------------------------------------------------

def _mk_category(email: str, title: str) -> int:
    return int(_shell(
        f"from feusers.models import FeUser; from budget.models import Category; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"c, _ = Category.objects.get_or_create(owning_feuser=u, title='{title}'); "
        f"print(c.pk)"
    ))


def _mk_tag(email: str, title: str) -> int:
    return int(_shell(
        f"from feusers.models import FeUser; from budget.models import Tag; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"t, _ = Tag.objects.get_or_create(owning_feuser=u, title='{title}'); "
        f"print(t.pk)"
    ))


def _overlay_category_title(expense_pk: int, email: str) -> str:
    """Return the category title in the overlay, or empty string."""
    return _shell(
        f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"o = ExpenseDataOverlay.objects.filter(expense_id={expense_pk}, feuser=u).first(); "
        f"print(o.category.title if o and o.category else '')"
    )


def _overlay_tag_titles(expense_pk: int, email: str) -> list[str]:
    """Return sorted tag titles from the overlay."""
    raw = _shell(
        f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"o = ExpenseDataOverlay.objects.filter(expense_id={expense_pk}, feuser=u).first(); "
        f"print(','.join(sorted(t.title for t in o.tags.all())) if o else '')"
    )
    return [t for t in raw.split(",") if t]


def _overlay_exists(expense_pk: int, email: str) -> bool:
    return _shell(
        f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"print(ExpenseDataOverlay.objects.filter(expense_id={expense_pk}, feuser=u).exists())"
    ).strip() == "True"


def _expense_category_title(expense_pk: int) -> str:
    return _shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.get(pk={expense_pk}); "
        f"print(e.category.title if e.category else '')"
    )


def _expense_tag_titles(expense_pk: int) -> list[str]:
    raw = _shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.get(pk={expense_pk}); "
        f"print(','.join(sorted(t.title for t in e.tags.all())))"
    )
    return [t for t in raw.split(",") if t]


def _create_expense_with_other_payer(
    creator_email: str, owner_email: str,
    title: str = "Other Payer Exp",
    category_pk: int = 0,
    tag_pks: list[int] | None = None,
    participant_pks: list[int] | None = None,
) -> int:
    """
    Simulate what expense_create does when upfront_type='feuser':
    expense saved with owner's tags/category (reconciled), overlay for creator.
    Uses the service layer directly, mirroring the view logic.
    """
    tag_pks = tag_pks or []
    participant_pks = participant_pks or []
    tag_set = ", ".join(str(pk) for pk in tag_pks)
    participant_set = ", ".join(
        f"{{'type':'feuser','id':{pk},'share_percent':50}}" for pk in participant_pks
    )
    return int(_shell(
        f"from feusers.models import FeUser; from budget.models import Expense, Category, Tag; "
        f"from buddies.services import BuddyExpenseService; "
        f"from budget.services import upsert_overlay, create_participant_overlays; "
        f"creator = FeUser.objects.get(email='{creator_email}'); "
        f"owner   = FeUser.objects.get(email='{owner_email}'); "
        # Build expense owned by 'other' (owner), but with creator's cat/tags
        f"e = Expense.objects.create(owning_feuser=owner, title='{title}', "
        f"  type='expense', value='100.00', settled=False, buddy_approved=False, "
        f"  category_id={category_pk if category_pk else 'None'}); "
        f"e.tags.set([{tag_set}]); "
        # Save overlay for creator with original selection
        f"creating_category = e.category; "
        f"creating_tags = list(e.tags.all()); "
        f"upsert_overlay(e, creator, creating_category, creating_tags); "
        # Reconcile expense to owner's objects
        f"BuddyExpenseService.reconcile_categories_tags(e, owner); "
        f"e.save(update_fields=['category']); "
        # Set spendings (creator as participant)
        f"from buddies.models import BuddySpending; from decimal import Decimal; "
        f"BuddySpending.objects.create(expense=e, participant_feuser=creator, share_percent=Decimal('50')); "
        + (f"" if not participant_pks else
           "".join(f"BuddySpending.objects.create(expense=e, participant_feuser_id={pk}, share_percent=Decimal('50')); "
                   for pk in participant_pks)) +
        f"create_participant_overlays(e); "
        f"print(e.pk)"
    ))


# ===========================================================================
# C1: Expense creation with another feuser as upfront payer
# ===========================================================================

class TestCreationWithOtherPayer:
    """[C1] Category/tags reconciled to owner; overlay created for creating feuser."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        creator = setup_user(driver, w, first_name="Crea", last_name="Tor")
        owner   = setup_user(None, None, first_name="Own", last_name="Er")
        _create_buddy_link(creator["email"], owner["email"])

        # Same title on both sides -> match
        _mk_category(creator["email"], "Food")
        _mk_category(owner["email"],   "Food")
        creator_tag_pk = _mk_tag(creator["email"], "Groceries")
        _mk_tag(owner["email"], "Groceries")
        # Tag only on creator side -> no match for owner
        _mk_tag(creator["email"], "OnlyCreator")

        # Get the creator's category pk to pass to _create_expense_with_other_payer
        creator_cat_pk = int(_shell(
            f"from feusers.models import FeUser; from budget.models import Category; "
            f"u = FeUser.objects.get(email='{creator['email']}'); "
            f"print(Category.objects.get(owning_feuser=u, title='Food').pk)"
        ))

        exp_pk = _create_expense_with_other_payer(
            creator["email"], owner["email"],
            title="C1 Expense",
            category_pk=creator_cat_pk,
            tag_pks=[creator_tag_pk, _mk_tag(creator["email"], "OnlyCreator")],
        )
        yield {
            "creator": creator, "owner": owner,
            "exp_pk": exp_pk, "creator_cat_pk": creator_cat_pk,
        }
        cleanup_user(creator["email"])
        cleanup_user(owner["email"])

    def test_expense_category_reconciled_to_owner(self, ctx):
        """Expense's category is the owner's 'Food', not the creator's."""
        assert _expense_category_title(ctx["exp_pk"]) == "Food", \
            "[C1] Expense category must be reconciled to owner's matching category"

    def test_expense_only_has_matched_tags(self, ctx):
        """Non-matching tag 'OnlyCreator' is dropped; 'Groceries' remains."""
        assert _expense_tag_titles(ctx["exp_pk"]) == ["Groceries"], \
            "[C1] Expense must only contain tags that matched on the owner's side"

    def test_overlay_created_for_creator(self, ctx):
        assert _overlay_exists(ctx["exp_pk"], ctx["creator"]["email"]), \
            "[C1] Overlay must exist for the creating feuser"

    def test_overlay_contains_creator_original_category(self, ctx):
        assert _overlay_category_title(ctx["exp_pk"], ctx["creator"]["email"]) == "Food", \
            "[C1] Overlay must hold creator's original category"

    def test_overlay_contains_all_creator_original_tags(self, ctx):
        titles = _overlay_tag_titles(ctx["exp_pk"], ctx["creator"]["email"])
        assert "Groceries" in titles, "[C1] Overlay must contain creator's matched tag"
        assert "OnlyCreator" in titles, "[C1] Overlay must contain creator's unmatched tag too"

    def test_no_overlay_for_owner(self, ctx):
        """Owner's data lives on the expense itself; no overlay needed."""
        assert not _overlay_exists(ctx["exp_pk"], ctx["owner"]["email"]), \
            "[C1] Owner must not have an overlay"


# ===========================================================================
# C2: No overlay when creating feuser had no category/tags
# ===========================================================================

class TestNoOverlayWhenCreatorHasNone:
    """[C2] If the creating feuser selected neither category nor tags, no overlay."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        creator = setup_user(driver, w, first_name="NoCat", last_name="Creator")
        owner   = setup_user(None, None, first_name="NoCat", last_name="Owner")
        _create_buddy_link(creator["email"], owner["email"])
        exp_pk = _create_expense_with_other_payer(
            creator["email"], owner["email"], title="C2 No Overlay Exp",
        )
        yield {"creator": creator, "owner": owner, "exp_pk": exp_pk}
        cleanup_user(creator["email"])
        cleanup_user(owner["email"])

    def test_no_overlay_for_creator_when_nothing_selected(self, ctx):
        assert not _overlay_exists(ctx["exp_pk"], ctx["creator"]["email"]), \
            "[C2] No overlay must be created when creator had no category or tags"


# ===========================================================================
# C3: Auto-overlay for other real-user participants with matching tags
# ===========================================================================

class TestAutoOverlayForParticipants:
    """[C3] Participants with title-matching tags/category get auto-overlays on creation."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="AutoOv", last_name="Owner")
        p1    = setup_user(None, None, first_name="AutoOv", last_name="P1")
        p2    = setup_user(None, None, first_name="AutoOv", last_name="P2")

        # Owner has category + tag
        _mk_category(owner["email"], "Travel")
        owner_tag_pk = _mk_tag(owner["email"], "Trip")

        # P1 has the same tag title -> should get overlay
        _mk_tag(p1["email"], "Trip")

        # P2 has no matching tags -> no overlay
        _mk_tag(p2["email"], "Unrelated")

        p1_pk = int(_get_pk(p1["email"]))
        p2_pk = int(_get_pk(p2["email"]))

        owner_cat_pk = int(_shell(
            f"from feusers.models import FeUser; from budget.models import Category; "
            f"u = FeUser.objects.get(email='{owner['email']}'); "
            f"print(Category.objects.get(owning_feuser=u, title='Travel').pk)"
        ))

        # Create expense owned by owner, with p1 and p2 as participants
        exp_pk = int(_shell(
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"from buddies.models import BuddySpending; from decimal import Decimal; "
            f"from budget.services import create_participant_overlays; "
            f"o = FeUser.objects.get(email='{owner['email']}'); "
            f"e = Expense.objects.create(owning_feuser=o, title='C3 Exp', "
            f"  type='expense', value='90.00', settled=False, category_id={owner_cat_pk}); "
            f"e.tags.set([{owner_tag_pk}]); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={p1_pk}, share_percent=Decimal('33')); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={p2_pk}, share_percent=Decimal('33')); "
            f"create_participant_overlays(e); "
            f"print(e.pk)"
        ))

        yield {
            "owner": owner, "p1": p1, "p2": p2, "exp_pk": exp_pk,
        }
        cleanup_user(owner["email"])
        cleanup_user(p1["email"])
        cleanup_user(p2["email"])

    def test_participant_with_matching_tag_gets_overlay(self, ctx):
        assert _overlay_exists(ctx["exp_pk"], ctx["p1"]["email"]), \
            "[C3] Participant with matching tag must get auto-overlay"

    def test_auto_overlay_contains_matched_tag(self, ctx):
        assert "Trip" in _overlay_tag_titles(ctx["exp_pk"], ctx["p1"]["email"]), \
            "[C3] Auto-overlay must contain participant's matching tag"

    def test_participant_without_match_gets_no_overlay(self, ctx):
        assert not _overlay_exists(ctx["exp_pk"], ctx["p2"]["email"]), \
            "[C3] Participant without matching tags must not get an overlay"

    def test_owner_has_no_overlay(self, ctx):
        assert not _overlay_exists(ctx["exp_pk"], ctx["owner"]["email"]), \
            "[C3] Owner must not get a participant overlay"


# ===========================================================================
# C4a: Upfront payer change — old owner gets overlay
# ===========================================================================

class TestPayerChangeOldOwnerGetsOverlay:
    """[C4] After changing upfront payer, old owner has overlay with old category/tag."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        old_owner = setup_user(driver, w, first_name="OldOw", last_name="A")
        new_owner = setup_user(None, None, first_name="NewOw", last_name="B")
        _create_buddy_link(old_owner["email"], new_owner["email"])

        _mk_category(old_owner["email"], "Holiday")
        old_tag_pk = _mk_tag(old_owner["email"], "Summer")
        _mk_category(new_owner["email"], "Holiday")
        _mk_tag(new_owner["email"], "Summer")

        old_cat_pk = int(_shell(
            f"from feusers.models import FeUser; from budget.models import Category; "
            f"u = FeUser.objects.get(email='{old_owner['email']}'); "
            f"print(Category.objects.get(owning_feuser=u, title='Holiday').pk)"
        ))
        new_owner_pk = int(_get_pk(new_owner["email"]))

        # Create expense owned by old_owner with category+tag
        exp_pk = int(_shell(
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"from buddies.models import BuddySpending; from decimal import Decimal; "
            f"o = FeUser.objects.get(email='{old_owner['email']}'); "
            f"e = Expense.objects.create(owning_feuser=o, title='C4a Exp', "
            f"  type='expense', value='80.00', settled=False, category_id={old_cat_pk}); "
            f"e.tags.set([{old_tag_pk}]); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={new_owner_pk}, "
            f"  share_percent=Decimal('50')); "
            f"print(e.pk)"
        ))

        # Change upfront payer to new_owner
        _shell(
            f"from budget.models import Expense; from feusers.models import FeUser; "
            f"from buddies.services import BuddyExpenseService; "
            f"e = Expense.objects.get(pk={exp_pk}); "
            f"new = FeUser.objects.get(pk={new_owner_pk}); "
            f"BuddyExpenseService.change_upfront_payer(e, new_payer_feuser=new)"
        )

        yield {"old_owner": old_owner, "new_owner": new_owner, "exp_pk": exp_pk}
        cleanup_user(old_owner["email"])
        cleanup_user(new_owner["email"])

    def test_old_owner_gets_overlay(self, ctx):
        assert _overlay_exists(ctx["exp_pk"], ctx["old_owner"]["email"]), \
            "[C4] Old owner must have an overlay after upfront-payer change"

    def test_old_owner_overlay_has_old_category(self, ctx):
        assert _overlay_category_title(ctx["exp_pk"], ctx["old_owner"]["email"]) == "Holiday", \
            "[C4] Old owner's overlay must preserve the pre-transfer category"

    def test_old_owner_overlay_has_old_tag(self, ctx):
        assert "Summer" in _overlay_tag_titles(ctx["exp_pk"], ctx["old_owner"]["email"]), \
            "[C4] Old owner's overlay must preserve the pre-transfer tag"

    def test_expense_now_owned_by_new_owner(self, ctx):
        owner_email = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['exp_pk']}).owning_feuser.email)"
        )
        assert owner_email == ctx["new_owner"]["email"], \
            "[C4] Expense must now be owned by the new owner"

    def test_expense_category_reconciled_to_new_owner(self, ctx):
        assert _expense_category_title(ctx["exp_pk"]) == "Holiday", \
            "[C4] Expense category must be reconciled to new owner's matching category"

    def test_new_owner_has_no_overlay(self, ctx):
        assert not _overlay_exists(ctx["exp_pk"], ctx["new_owner"]["email"]), \
            "[C4] New owner must not have an overlay (they are now the owner)"


# ===========================================================================
# C4b: Payer change — new owner's existing overlay is applied to expense
# ===========================================================================

class TestPayerChangeExistingOverlayApplied:
    """[C4] When new owner already has an overlay, it is applied to the expense."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        old_owner = setup_user(driver, w, first_name="ApplOld", last_name="A")
        new_owner = setup_user(None, None, first_name="ApplNew", last_name="B")
        _create_buddy_link(old_owner["email"], new_owner["email"])

        # New owner has a specific category + tag for their overlay
        new_cat_pk  = _mk_category(new_owner["email"], "NewOwnerCat")
        new_tag_pk  = _mk_tag(new_owner["email"], "NewOwnerTag")
        new_owner_pk = int(_get_pk(new_owner["email"]))

        exp_pk = int(_shell(
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"from buddies.models import BuddySpending; from decimal import Decimal; "
            f"o = FeUser.objects.get(email='{old_owner['email']}'); "
            f"e = Expense.objects.create(owning_feuser=o, title='C4b Exp', "
            f"  type='expense', value='60.00', settled=False); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={new_owner_pk}, "
            f"  share_percent=Decimal('50')); "
            f"print(e.pk)"
        ))

        # Pre-create overlay for new owner (simulating they set it earlier)
        _shell(
            f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay, Category, Tag; "
            f"u = FeUser.objects.get(pk={new_owner_pk}); "
            f"o, _ = ExpenseDataOverlay.objects.get_or_create(expense_id={exp_pk}, feuser=u); "
            f"o.category_id = {new_cat_pk}; o.save(); "
            f"o.tags.set([{new_tag_pk}])"
        )

        # Change upfront payer
        _shell(
            f"from budget.models import Expense; from feusers.models import FeUser; "
            f"from buddies.services import BuddyExpenseService; "
            f"e = Expense.objects.get(pk={exp_pk}); "
            f"new = FeUser.objects.get(pk={new_owner_pk}); "
            f"BuddyExpenseService.change_upfront_payer(e, new_payer_feuser=new)"
        )

        yield {"old_owner": old_owner, "new_owner": new_owner, "exp_pk": exp_pk}
        cleanup_user(old_owner["email"])
        cleanup_user(new_owner["email"])

    def test_expense_has_new_owner_category(self, ctx):
        assert _expense_category_title(ctx["exp_pk"]) == "NewOwnerCat", \
            "[C4b] New owner's overlay category must be applied to the expense"

    def test_expense_has_new_owner_tag(self, ctx):
        assert "NewOwnerTag" in _expense_tag_titles(ctx["exp_pk"]), \
            "[C4b] New owner's overlay tag must be applied to the expense"

    def test_new_owner_overlay_is_deleted(self, ctx):
        assert not _overlay_exists(ctx["exp_pk"], ctx["new_owner"]["email"]), \
            "[C4b] New owner's overlay must be deleted after being applied"


# ===========================================================================
# C5: No snapshot overlay when expense had no category/tags before transfer
# ===========================================================================

class TestNoSnapshotWhenExpenseHasNoCatTags:
    """[C5] Old owner does not get an overlay when the expense had no category/tags."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        old_owner = setup_user(driver, w, first_name="NoSnap", last_name="Old")
        new_owner = setup_user(None, None, first_name="NoSnap", last_name="New")
        _create_buddy_link(old_owner["email"], new_owner["email"])
        new_owner_pk = int(_get_pk(new_owner["email"]))

        exp_pk = int(_shell(
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"from buddies.models import BuddySpending; from decimal import Decimal; "
            f"o = FeUser.objects.get(email='{old_owner['email']}'); "
            f"e = Expense.objects.create(owning_feuser=o, title='C5 Exp', "
            f"  type='expense', value='50.00', settled=False); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={new_owner_pk}, "
            f"  share_percent=Decimal('50')); "
            f"print(e.pk)"
        ))

        _shell(
            f"from budget.models import Expense; from feusers.models import FeUser; "
            f"from buddies.services import BuddyExpenseService; "
            f"e = Expense.objects.get(pk={exp_pk}); "
            f"new = FeUser.objects.get(pk={new_owner_pk}); "
            f"BuddyExpenseService.change_upfront_payer(e, new_payer_feuser=new)"
        )

        yield {"old_owner": old_owner, "new_owner": new_owner, "exp_pk": exp_pk}
        cleanup_user(old_owner["email"])
        cleanup_user(new_owner["email"])

    def test_no_overlay_for_old_owner_when_expense_was_empty(self, ctx):
        assert not _overlay_exists(ctx["exp_pk"], ctx["old_owner"]["email"]), \
            "[C5] No overlay must be created for old owner when expense had no category/tags"
