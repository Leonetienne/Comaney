"""
Settlement edit/copy/delete restrictions.

Scenarios covered:
- Clone (copy) button is absent for settlement expenses in the expense list
- Clone via POST is blocked server-side for settlements
- In the personal buddy summary, edit button is absent for settlements
- In the personal buddy summary, delete button IS present for unapproved settlements
  and for approved settlements where the creditor is an offline member
- In the personal buddy summary, delete button is absent for approved real-user settlements
- Deleting an unapproved settlement sends a cancellation email to the creditor
- Approved real-user settlements cannot be deleted even via direct POST
- Bulk delete silently skips settlement expenses
- In the group view, edit button is present for pending real-user settlements (debtor can still edit)
- In the group view, edit button is absent for approved real-user settlements
- In the group view, edit button IS present for admin editing a dummy-creditor settlement
- In the group view, approved real-user settlements cannot be deleted by the debtor
"""
import time

import pytest

from helpers import _url, setup_user, cleanup_user, fetch_email, mailpit_seen_ids, api_get
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk,
    _create_personal_expense_with_buddy, _create_group, _add_group_member,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _create_feuser_settlement(debtor_email: str, creditor_pk: int, value: str = "50.00",
                               approved: bool = False, group_pk: int = None) -> str:
    """Create a settlement from debtor to a real-user creditor; return pk."""
    if group_pk:
        group_load = (
            f"from buddies.models import BuddyGroup; "
            f"grp = BuddyGroup.objects.get(pk={group_pk}); "
        )
        group_arg = "buddy_group=grp, "
    else:
        group_load = ""
        group_arg = ""
    return _shell(
        f"from budget.expense_factory import create_expense; "
        f"from feusers.models import FeUser; from budget.models import TransactionType; "
        f"from decimal import Decimal; import datetime; "
        f"{group_load}"
        f"a = FeUser.objects.get(email='{debtor_email}'); "
        f"e = create_expense(owning_feuser=a, title='Test Settlement', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  date_due=datetime.date.today(), settled=True, "
        f"  is_buddies_settlement=True, buddy_approved={'True' if approved else 'False'}, "
        f"  {group_arg}"
        f"  buddy_spendings=[{{'type': 'feuser', 'id': {creditor_pk}, 'share_percent': 100}}]); "
        f"print(e.pk)"
    )


def _create_dummy_settlement(debtor_email: str, dummy_pk: int, value: str = "25.00",
                              approved: bool = True, group_pk: int = None) -> str:
    """Create a settlement from debtor to an offline member (dummy); return pk."""
    if group_pk:
        group_load = (
            f"from buddies.models import BuddyGroup; "
            f"grp = BuddyGroup.objects.get(pk={group_pk}); "
        )
        group_arg = "buddy_group=grp, "
    else:
        group_load = ""
        group_arg = ""
    return _shell(
        f"from budget.expense_factory import create_expense; "
        f"from feusers.models import FeUser; from budget.models import TransactionType; "
        f"from decimal import Decimal; import datetime; "
        f"{group_load}"
        f"a = FeUser.objects.get(email='{debtor_email}'); "
        f"e = create_expense(owning_feuser=a, title='Dummy Settlement', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  date_due=datetime.date.today(), settled=True, "
        f"  is_buddies_settlement=True, buddy_approved={'True' if approved else 'False'}, "
        f"  {group_arg}"
        f"  buddy_spendings=[{{'type': 'dummy', 'id': {dummy_pk}, 'share_percent': 100}}]); "
        f"print(e.pk)"
    )


def _create_personal_dummy(owner_email: str, name: str = "Offline Creditor") -> str:
    """Create a personal DummyUser owned by owner; return pk."""
    return _shell(
        f"from buddies.models import DummyUser; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"d = DummyUser.objects.create(owning_feuser=u, display_name='{name}'); "
        f"print(d.pk)"
    )


def _create_group_dummy(group_pk: int, name: str = "Offline Member") -> str:
    """Create a DummyUser for a group; return pk."""
    return _shell(
        f"from buddies.models import DummyUser, BuddyGroup, BuddyGroupMember; "
        f"g = BuddyGroup.objects.get(pk={group_pk}); "
        f"d = DummyUser.objects.create(owning_group=g, display_name='{name}'); "
        f"BuddyGroupMember.objects.create(group=g, dummy=d); "
        f"print(d.pk)"
    )


# ---------------------------------------------------------------------------
# 1. Clone button absent for settlements in the expense list
# ---------------------------------------------------------------------------

class TestCloneButtonAbsentForSettlements:
    """The Clone button must not appear for settlement expenses in the expense list."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Clone", last_name="Debtor")
        b = setup_user(None, None, first_name="Clone", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_feuser_settlement(a["email"], b_pk))
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_clone_button_absent_in_expense_list(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        # The clone URL pattern should not appear next to the settlement
        clone_action = f"/budget/expenses/{ctx['exp_pk']}/clone/"
        assert clone_action not in driver.page_source, \
            "Clone button must not appear for settlement expenses in the expense list"

    def test_clone_post_is_blocked_server_side(self, driver, w, ctx):
        """A direct clone POST should redirect without creating a clone."""
        seen_before = {e["id"] for e in api_get("/api/v1/expenses/", ctx["a"]).json()["expenses"]}
        driver.execute_script(
            f"var f = document.createElement('form');"
            f"f.method = 'POST';"
            f"f.action = '/budget/expenses/{ctx['exp_pk']}/clone/';"
            f"var csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t = document.createElement('input');"
            f"t.name = 'csrfmiddlewaretoken'; t.value = csrf; f.appendChild(t);"
            f"document.body.appendChild(f); f.submit();"
        )
        time.sleep(2)
        current_ids = {e["id"] for e in api_get("/api/v1/expenses/", ctx["a"]).json()["expenses"]}
        assert current_ids == seen_before, \
            "Cloning a settlement must not create a new expense"


# ---------------------------------------------------------------------------
# 2. Personal buddy summary: edit button absent, delete button present/absent
# ---------------------------------------------------------------------------

class TestPersonalBuddySummaryButtons:
    """Verify edit/delete button behaviour for settlements in the personal buddy summary."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Pers", last_name="Debtor")
        b = setup_user(None, None, first_name="Pers", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        a_pk = int(_get_pk(a["email"]))
        dummy_pk = int(_create_personal_dummy(a["email"]))
        # Unapproved real-user settlement
        unapproved_pk = int(_create_feuser_settlement(a["email"], b_pk, value="40.00"))
        # Approved dummy-creditor settlement
        dummy_settle_pk = int(_create_dummy_settlement(a["email"], dummy_pk, value="20.00",
                                                        approved=True))
        # Give A a debt to B so the settlement makes contextual sense
        _create_personal_expense_with_buddy(
            owner_email=b["email"], participant_pk=a_pk,
            title="Debt Source", value="80.00", share="50.0", approved=True,
        )
        yield {
            "a": a, "b": b,
            "unapproved_pk": unapproved_pk,
            "dummy_settle_pk": dummy_settle_pk,
        }
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_edit_button_present_for_unapproved_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        edit_url = f"/budget/expenses/{ctx['unapproved_pk']}/edit/"
        assert edit_url in driver.page_source, \
            "Edit button must appear for an unapproved real-user settlement in buddy summary"

    def test_delete_button_present_for_unapproved_settlement(self, driver, w, ctx):
        delete_url = f"/budget/expenses/{ctx['unapproved_pk']}/delete/"
        assert delete_url in driver.page_source, \
            "Delete button must appear for an unapproved settlement in buddy summary"

    def test_edit_button_present_for_dummy_settlement(self, driver, w, ctx):
        edit_url = f"/budget/expenses/{ctx['dummy_settle_pk']}/edit/"
        assert edit_url in driver.page_source, \
            "Edit button must appear for dummy-creditor settlement in buddy summary (always editable)"

    def test_delete_button_present_for_dummy_settlement(self, driver, w, ctx):
        delete_url = f"/budget/expenses/{ctx['dummy_settle_pk']}/delete/"
        assert delete_url in driver.page_source, \
            "Delete button must appear for approved dummy-creditor settlement in buddy summary"


# ---------------------------------------------------------------------------
# 3. Approved real-user settlement: no delete button, server blocks deletion
# ---------------------------------------------------------------------------

class TestApprovedRealUserSettlementNotDeletable:
    """An approved real-user settlement cannot be deleted from any UI surface."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="App", last_name="Debtor")
        b = setup_user(None, None, first_name="App", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_feuser_settlement(a["email"], b_pk, value="30.00", approved=True))
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_delete_button_absent_in_expense_list(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        delete_action = f"/budget/expenses/{ctx['exp_pk']}/delete/"
        assert delete_action not in driver.page_source, \
            "Delete button must not appear for approved real-user settlement in expense list"

    def test_delete_button_absent_in_buddy_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        delete_action = f"/budget/expenses/{ctx['exp_pk']}/delete/"
        assert delete_action not in driver.page_source, \
            "Delete button must not appear for approved real-user settlement in buddy summary"

    def test_direct_delete_post_is_rejected(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        time.sleep(1)
        driver.execute_script(
            f"var f = document.createElement('form');"
            f"f.method = 'POST';"
            f"f.action = '/budget/expenses/{ctx['exp_pk']}/delete/';"
            f"var csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t = document.createElement('input');"
            f"t.name = 'csrfmiddlewaretoken'; t.value = csrf; f.appendChild(t);"
            f"document.body.appendChild(f); f.submit();"
        )
        time.sleep(2)

    def test_approved_settlement_still_exists(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx["a"], params={"q": "Test Settlement"})
        assert any(e["id"] == ctx["exp_pk"] for e in resp.json()["expenses"]), \
            "Approved settlement must survive a delete attempt"


# ---------------------------------------------------------------------------
# 4. Deleting an unapproved settlement sends cancellation email to creditor
# ---------------------------------------------------------------------------

class TestUnapprovedSettlementCancellationEmail:
    """Deleting an unapproved settlement via the delete button sends B a cancellation email."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Carl", last_name="Canceller")
        b = setup_user(None, None, first_name="Vera", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        a_pk = int(_get_pk(a["email"]))
        _create_personal_expense_with_buddy(
            owner_email=b["email"], participant_pk=a_pk,
            title="Debt Source", value="100.00", share="50.0", approved=True,
        )
        exp_pk = int(_create_feuser_settlement(a["email"], b_pk, value="50.00"))
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_delete_button_present(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/delete/" in driver.page_source, \
            "Delete button must be present for unapproved settlement in buddy summary"

    def test_delete_sends_cancellation_email(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        driver.execute_script(
            f"var f = document.createElement('form');"
            f"f.method = 'POST';"
            f"f.action = '/budget/expenses/{ctx['exp_pk']}/delete/';"
            f"var csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t = document.createElement('input');"
            f"t.name = 'csrfmiddlewaretoken'; t.value = csrf; f.appendChild(t);"
            f"document.body.appendChild(f); f.submit();"
        )
        time.sleep(2)

    def test_settlement_is_deleted(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx["a"], params={"q": "Test Settlement"})
        assert not any(e["id"] == ctx["exp_pk"] for e in resp.json()["expenses"]), \
            "Settlement must be deleted after debtor removes it"

    def test_creditor_receives_cancellation_email(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "cancelled",
            ignore_ids=ctx.get("seen_before"),
        )
        assert "Carl Canceller" in body, "Cancellation email must name the debtor"
        assert "50" in body, "Cancellation email must mention the settlement amount"

    def test_cancellation_email_mentions_balance(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "cancelled",
            ignore_ids=ctx.get("seen_before"),
        )
        assert "balance" in body.lower() or "outstanding" in body.lower(), \
            "Cancellation email must state the balance remains unchanged"


# ---------------------------------------------------------------------------
# 5. Bulk delete silently skips settlements
# ---------------------------------------------------------------------------

class TestBulkDeleteSkipsSettlements:
    """Bulk-deleting a mix of normal and settlement expenses removes only the normal ones."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Bob", last_name="Bulker")
        b = setup_user(None, None, first_name="Ben", last_name="BulkCreditor")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        settle_pk = int(_create_feuser_settlement(a["email"], b_pk, value="20.00"))
        normal_pk = int(_shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; import datetime; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"e = create_expense(owning_feuser=a, title='Bulk Normal Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('10.00'), "
            f"  date_due=datetime.date.today(), settled=True); "
            f"print(e.pk)"
        ))
        yield {"a": a, "b": b, "settle_pk": settle_pk, "normal_pk": normal_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_bulk_delete_both(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/expenses/"))
        time.sleep(1)
        driver.execute_script(
            f"var f = document.createElement('form');"
            f"f.method = 'POST'; f.action = '/budget/expenses/bulk-action/';"
            f"var csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"[['csrfmiddlewaretoken', csrf], ['action', 'delete'],"
            f" ['uid', '{ctx['settle_pk']}'], ['uid', '{ctx['normal_pk']}']"
            f"].forEach(function([n,v]){{ var i=document.createElement('input');"
            f"i.name=n; i.value=v; f.appendChild(i); }});"
            f"document.body.appendChild(f); f.submit();"
        )
        time.sleep(2)

    def test_normal_expense_deleted(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx["a"], params={"q": "Bulk Normal Expense"})
        assert not any(e["title"] == "Bulk Normal Expense" for e in resp.json()["expenses"]), \
            "Normal expense must be deleted by bulk action"

    def test_settlement_survives_bulk_delete(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx["a"], params={"q": "Test Settlement"})
        assert any(e["id"] == ctx["settle_pk"] for e in resp.json()["expenses"]), \
            "Settlement expense must survive bulk delete"


# ---------------------------------------------------------------------------
# 6. Group view: edit button absent for real-user settlements
# ---------------------------------------------------------------------------

class TestGroupViewEditButtonAbsentForRealUserSettlement:
    """
    In the group expense breakdown, the Edit button must appear for pending
    real-user settlements (debtor can still correct them) and must not appear
    once the creditor has approved.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Grp", last_name="Debtor")
        b = setup_user(None, None, first_name="Grp", last_name="Creditor")
        grp_pk = int(_create_group(a["email"], "EditTestGroup"))
        _add_group_member(grp_pk, b["email"])
        b_pk = int(_get_pk(b["email"]))
        pending_pk = int(_create_feuser_settlement(
            a["email"], b_pk, value="40.00", approved=False, group_pk=grp_pk,
        ))
        approved_pk = int(_create_feuser_settlement(
            a["email"], b_pk, value="40.00", approved=True, group_pk=grp_pk,
        ))
        yield {"a": a, "b": b, "grp_pk": grp_pk,
               "pending_pk": pending_pk, "approved_pk": approved_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_edit_button_present_for_pending_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        edit_url = f"/budget/expenses/{ctx['pending_pk']}/edit/"
        assert edit_url in driver.page_source, \
            "Edit button must appear for a pending real-user settlement in group view (debtor can edit unapproved)"

    def test_edit_button_absent_for_approved_settlement(self, driver, w, ctx):
        edit_url = f"/budget/expenses/{ctx['approved_pk']}/edit/"
        assert edit_url not in driver.page_source, \
            "Edit button must not appear for an approved real-user settlement in group view"


# ---------------------------------------------------------------------------
# 7. Group view: edit button present for admin editing dummy-creditor settlement
# ---------------------------------------------------------------------------

class TestGroupViewEditButtonPresentForDummySettlement:
    """
    The group admin can edit a settlement to an offline member in their group.
    The Edit button must be visible and the edit page must open without redirect.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Gadm", last_name="Admin")
        grp_pk = int(_create_group(a["email"], "DummyEditGroup"))
        dummy_pk = int(_create_group_dummy(grp_pk, "Offline Creditor"))
        exp_pk = int(_create_dummy_settlement(
            a["email"], dummy_pk, value="30.00", approved=False, group_pk=grp_pk,
        ))
        yield {"a": a, "grp_pk": grp_pk, "dummy_pk": dummy_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])

    def test_edit_button_present_in_group_view(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        edit_url = f"/budget/expenses/{ctx['exp_pk']}/edit/"
        assert edit_url in driver.page_source, \
            "Edit button must appear for dummy-creditor settlement in group view for admin"

    def test_edit_page_opens_without_redirect(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.current_url, \
            "Edit page must not redirect for dummy-creditor settlements"


# ---------------------------------------------------------------------------
# 8. Group view: approved real-user settlement cannot be deleted by debtor
# ---------------------------------------------------------------------------

class TestGroupViewApprovedSettlementNotDeletable:
    """
    After the real-user creditor confirms a settlement, the debtor must not be
    able to delete it from the group view: no delete button and server rejects the POST.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Gdel", last_name="Debtor")
        b = setup_user(None, None, first_name="Gdel", last_name="Creditor")
        grp_pk = int(_create_group(a["email"], "DelTestGroup"))
        _add_group_member(grp_pk, b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_feuser_settlement(
            a["email"], b_pk, value="55.00", approved=True, group_pk=grp_pk,
        ))
        yield {"a": a, "b": b, "grp_pk": grp_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_delete_button_absent_in_group_view(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        delete_action = f"/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/"
        assert delete_action not in driver.page_source, \
            "Delete button must not appear for approved settlement in group view"

    def test_direct_group_delete_post_is_rejected(self, driver, w, ctx):
        driver.execute_script(
            f"var f = document.createElement('form');"
            f"f.method = 'POST';"
            f"f.action = '/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/';"
            f"var csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t = document.createElement('input');"
            f"t.name = 'csrfmiddlewaretoken'; t.value = csrf; f.appendChild(t);"
            f"document.body.appendChild(f); f.submit();"
        )
        time.sleep(2)

    def test_approved_settlement_still_exists_after_delete_attempt(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx["a"], params={"q": "Test Settlement"})
        assert any(e["id"] == ctx["exp_pk"] for e in resp.json()["expenses"]), \
            "Approved settlement must survive debtor's delete attempt from group view"


# ---------------------------------------------------------------------------
# 9. API: can_delete and is_buddies_settlement fields are correct
# ---------------------------------------------------------------------------

class TestApiCanDeleteField:
    """The expense API exposes is_buddies_settlement and can_delete correctly."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Fran", last_name="ApiChecker")
        b = setup_user(None, None, first_name="Gus", last_name="ApiCreditor")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        dummy_pk = int(_create_personal_dummy(a["email"]))
        unapproved_pk = int(_create_feuser_settlement(a["email"], b_pk, value="10.00"))
        approved_pk = int(_create_feuser_settlement(
            a["email"], b_pk, value="10.00", approved=True,
        ))
        dummy_pk_settle = int(_create_dummy_settlement(
            a["email"], dummy_pk, value="10.00", approved=True,
        ))
        yield {
            "a": a, "b": b,
            "unapproved_pk": unapproved_pk,
            "approved_pk": approved_pk,
            "dummy_settle_pk": dummy_pk_settle,
        }
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def _get_expense(self, ctx, pk):
        resp = api_get("/api/v1/expenses/", ctx["a"])
        return next((e for e in resp.json()["expenses"] if e["id"] == pk), None)

    def test_unapproved_settlement_can_delete_true(self, driver, w, ctx):
        exp = self._get_expense(ctx, ctx["unapproved_pk"])
        assert exp is not None
        assert exp["is_buddies_settlement"] is True
        assert exp["can_delete"] is True

    def test_approved_feuser_settlement_can_delete_false(self, driver, w, ctx):
        exp = self._get_expense(ctx, ctx["approved_pk"])
        assert exp is not None
        assert exp["is_buddies_settlement"] is True
        assert exp["can_delete"] is False

    def test_approved_dummy_settlement_can_delete_true(self, driver, w, ctx):
        exp = self._get_expense(ctx, ctx["dummy_settle_pk"])
        assert exp is not None
        assert exp["is_buddies_settlement"] is True
        assert exp["can_delete"] is True
