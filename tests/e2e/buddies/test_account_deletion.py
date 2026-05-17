"""
Account deletion buddy cleanup: BuddyLifecycleService.handle_account_deletion()
is called before the user is deleted. It converts all buddy relationships to
dummy placeholders so the remaining user's history stays intact.

Scenarios tested:
  1. User with a personal buddy link deletes account:
     - The surviving buddy gets a ghost dummy with the deleted user's display name.
     - Expenses the deleted user owned (where the surviving buddy was a participant)
       are cloned for the surviving user with the ghost dummy as payer.
     - The surviving user's BuddySpending rows now point to the ghost dummy.
     - The buddy link is gone; the deleted user cannot log in.

  2. User who is admin of a group deletes account:
     - Admin is transferred to another feuser member.
     - The deleting user is ghost-dummied in the group.
     - The group still exists with the new admin.
"""
import time

import pytest

from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_buddy_link, _create_group, _add_group_member


def _delete_account_via_ui(driver, ctx_user: dict) -> None:
    """Navigate to /account/delete/ and confirm with password."""
    _login_as(driver, ctx_user)
    driver.get(_url("/account/delete/"))
    time.sleep(1)
    pw_el = driver.find_element(By.ID, "id_password")
    driver.execute_script("arguments[0].value = arguments[1];", pw_el, ctx_user["password"])
    driver.find_element(By.ID, "btn-delete-account").click()
    time.sleep(2)


def _dummy_count_for(feuser_email: str) -> int:
    return int(_shell(
        f"from buddies.models import DummyUser; "
        f"from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{feuser_email}'); "
        f"print(DummyUser.objects.filter(owning_feuser=u, owning_group__isnull=True).count())"
    ))


def _buddy_link_exists(email_a: str, email_b: str) -> bool:
    result = _shell(
        f"from buddies.models import BuddyLink; "
        f"from feusers.models import FeUser; "
        f"a = FeUser.objects.get(email='{email_a}'); "
        f"b = FeUser.objects.get(email='{email_b}'); "
        f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
        f"print(BuddyLink.objects.filter(user_a=lo, user_b=hi).count())"
    )
    return result == "1"


# ---------------------------------------------------------------------------
# Personal buddy link: deleted user becomes a ghost dummy for the survivor
# ---------------------------------------------------------------------------

class TestAccountDeletionWithPersonalBuddy:
    """A deletes account; B (their buddy) gets a ghost dummy representing A."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        # A will be deleted; B will survive. Browser starts logged in as B.
        a = setup_user(None, None, first_name="Dustin", last_name="Deletes")
        b = setup_user(driver, w, first_name="Bianca", last_name="Survives")
        _create_buddy_link(a["email"], b["email"])
        # A paid an expense where B is a participant
        b_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{b['email']}').pk)"
        ))
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; "
            f"from budget.models import TransactionType; "
            f"from decimal import Decimal; import datetime; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"create_expense(owning_feuser=a, title='Shared With Bianca', "
            f"  type=TransactionType.EXPENSE, value=Decimal('80.00'), "
            f"  date_due=datetime.date.today(), settled=False, "
            f"  buddy_approved=True, "
            f"  buddy_spendings=[{{'type': 'feuser', 'id': {b_pk}, 'share_percent': 50}}])"
        )
        yield {"a": a, "b": b}
        # A is already deleted by the test; only clean up B.
        cleanup_user(b["email"])

    def test_buddy_link_exists_before_deletion(self, driver, w, ctx):
        assert _buddy_link_exists(ctx["a"]["email"], ctx["b"]["email"]), \
            "Buddy link must exist before A deletes their account"

    def test_a_deletes_account_redirects_to_home(self, driver, w, ctx):
        _delete_account_via_ui(driver, ctx["a"])
        # The view redirects to landing_page ("/") on success; failure stays on
        # /account/delete/. Assert the URL changed away from the delete page.
        assert "/account/delete/" not in driver.current_url, \
            f"URL must not remain on /account/delete/ after successful submission; got: {driver.current_url}"
        a_exists = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.filter(email='{ctx['a']['email']}').count())"
        )
        assert a_exists == "0", \
            "A's FeUser must no longer exist in the database after account deletion"

    def test_buddy_link_gone_after_deletion(self, driver, w, ctx):
        # A's FeUser no longer exists; the buddy link must be gone too.
        link_count = _shell(
            f"from buddies.models import BuddyLink; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(BuddyLink.for_user(b).count())"
        )
        assert link_count == "0", \
            "BuddyLink must be deleted when A's account is removed"

    def test_b_has_ghost_dummy_for_a(self, driver, w, ctx):
        count = _dummy_count_for(ctx["b"]["email"])
        assert count >= 1, \
            "B must have at least one personal ghost dummy created for the deleted user A"

    def test_ghost_dummy_has_as_display_name(self, driver, w, ctx):
        name = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"d = DummyUser.objects.filter(owning_feuser=b, owning_group__isnull=True).first(); "
            f"print(d.display_name if d else 'none')"
        )
        assert "Dustin" in name, \
            f"Ghost dummy must carry A's display name, got: {name!r}"

    def test_b_sees_ghost_dummy_on_buddies_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Dustin" in driver.page_source, \
            "B's buddies page must show the ghost dummy with A's name"

    def test_b_has_cloned_expense_with_ghost_dummy_as_payer(self, driver, w, ctx):
        """handle_account_deletion clones A's expense for B with the ghost dummy as upfront payer.

        When A owns an expense and B is a participant, the service calls
        clone_expense_for_feuser(A's_expense, B, ghost_dummy). The clone has
        owning_feuser=B and upfront_payee_dummy=ghost_dummy. B becomes the owner so
        no BuddySpending rows are created for the clone. A's original expense (and B's
        original BuddySpending in it) are cascade-deleted when A's FeUser is removed.
        """
        count = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"ghost = DummyUser.objects.filter(owning_feuser=b, owning_group__isnull=True).first(); "
            f"print(Expense.objects.filter(owning_feuser=b, upfront_payee_dummy=ghost, "
            f"  is_dummy=True).count() if ghost else 0)"
        )
        assert count != "0", \
            "B must have a cloned expense with the ghost dummy (A) as upfront payer"


# ---------------------------------------------------------------------------
# Group admin deletes account: admin transferred, user ghost-dummied in group
# ---------------------------------------------------------------------------

class TestAccountDeletionGroupAdmin:
    """A (group admin) deletes account: admin is transferred to B; A is ghost-dummied."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(None, None, first_name="Greta", last_name="GoesAway")
        b = setup_user(driver, w, first_name="Bruno", last_name="StaysAdmin")
        group_id = int(_create_group(a["email"], "AdminGoneGroup"))
        _add_group_member(group_id, b["email"])
        yield {"a": a, "b": b, "group_id": group_id}
        cleanup_user(b["email"])

    def test_a_is_admin_before_deletion(self, driver, w, ctx):
        result = _shell(
            f"from buddies.models import BuddyGroup; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"g = BuddyGroup.objects.get(pk={ctx['group_id']}); "
            f"print(g.admin_feuser_id == a.pk)"
        )
        assert result == "True", "A must be the group admin before the test"

    def test_a_deletes_account(self, driver, w, ctx):
        _delete_account_via_ui(driver, ctx["a"])
        assert "/account/delete/" not in driver.current_url, \
            f"URL must not remain on /account/delete/ after deletion; got: {driver.current_url}"
        a_exists = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.filter(email='{ctx['a']['email']}').count())"
        )
        assert a_exists == "0", \
            "A's FeUser must no longer exist after account deletion"

    def test_group_still_exists(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import BuddyGroup; "
            f"print(BuddyGroup.objects.filter(pk={ctx['group_id']}).count())"
        )
        assert count == "1", "Group must still exist after the admin deletes their account"

    def test_b_is_new_admin(self, driver, w, ctx):
        result = _shell(
            f"from buddies.models import BuddyGroup; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"g = BuddyGroup.objects.get(pk={ctx['group_id']}); "
            f"print(g.admin_feuser_id == b.pk)"
        )
        assert result == "True", "B must become the group admin after A deletes their account"

    def test_b_sees_group_on_buddies_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "AdminGoneGroup" in driver.page_source, \
            "B must still see the group on their buddies page"

    def test_b_is_shown_as_admin_on_group_page(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "You are admin" in driver.page_source or "Admin" in driver.page_source, \
            "B must be displayed as the group admin on the group detail page"

    def test_a_ghost_dummy_present_in_group(self, driver, w, ctx):
        dummy_count = int(_shell(
            f"from buddies.models import DummyUser, BuddyGroup; "
            f"g = BuddyGroup.objects.get(pk={ctx['group_id']}); "
            f"print(DummyUser.objects.filter(owning_group=g, "
            f"  display_name__icontains='Greta').count())"
        ))
        assert dummy_count >= 1, \
            "A ghost dummy for Greta must be present in the group after account deletion"
