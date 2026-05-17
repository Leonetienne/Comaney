"""
Settlement edit/delete rules for unapproved settlements and offline-member settlements.

Rule: the creator (debtor) can edit OR delete a settlement as long as it is not yet approved.
In both cases, the creditor receives a notification email.
Offline-member (dummy) settlements are always editable/deletable (dummy can never confirm).
In groups, only the admin can manage offline-member expenses.

Bugs covered:
  [G1] Group: no edit button for unapproved real-user settlement
  [G2] Group: no cancellation email on unapproved settlement deletion
  [D1] Direct: settlement to offline buddy - no edit button
  [D2] Direct: deletion redirects to /budget/expenses/ instead of /buddies/
  [D3] Direct: settlement FROM offline buddy (is_dummy=True) - neither editable nor deletable
  [D4] Direct: settlement to real user (unapproved) - no edit button
  [D5] Direct: real-user settlement delete redirects to /budget/expenses/ instead of /buddies/
  [U1] UI: creditor dropdown on /buddies/ - offline buddies not labelled "(offline buddy)"
  [U2] UI: debtor dropdown on /buddies/ - offline members labelled "(offline member)" not "(offline buddy)"
  [G3] Group: admin cannot edit unapproved settlement FROM offline member TO actual user
  [G4] Cancellation/update emails name the admin instead of the offline member as debtor
  [E1] Endpoint: forged edit POST accepted for approved direct real-user settlement
  [E2] Endpoint: forged delete POST accepted for approved direct real-user settlement
  [E3] Endpoint: forged edit POST accepted for approved group real-user settlement
  [E4] Endpoint: forged delete POST accepted for approved group real-user settlement
  [E5] Endpoint: forged edit POST accepted for approved dummy-debtor group settlement
  [G18] Group: non-admin debtor (and admin) can edit approved settlement to group dummy via forged URL
  [G19] Group: non-admin debtor (and admin) can delete approved settlement to group dummy
"""
import time

import pytest

from helpers import _url, setup_user, cleanup_user, fetch_email, mailpit_seen_ids, api_get
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk,
    _create_personal_expense_with_buddy, _create_group, _add_group_member,
)


# ---------------------------------------------------------------------------
# Test-local shell helpers
# ---------------------------------------------------------------------------

def _mk_feuser_settlement(debtor_email: str, creditor_pk: int, value: str = "50.00",
                           approved: bool = False, group_pk: int = None) -> int:
    group_clause = (
        f"from buddies.models import BuddyGroup; grp=BuddyGroup.objects.get(pk={group_pk}); "
        if group_pk else ""
    )
    group_arg = "buddy_group=grp, " if group_pk else ""
    return int(_shell(
        f"from budget.expense_factory import create_expense; "
        f"from feusers.models import FeUser; from budget.models import TransactionType; "
        f"from decimal import Decimal; import datetime; "
        f"{group_clause}"
        f"a=FeUser.objects.get(email='{debtor_email}'); "
        f"e=create_expense(owning_feuser=a, title='FeuserSettlement', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  date_due=datetime.date.today(), settled=True, notify=False, "
        f"  is_buddies_settlement=True, buddy_approved={'True' if approved else 'False'}, "
        f"  {group_arg}"
        f"  buddy_spendings=[{{'type':'feuser','id':{creditor_pk},'share_percent':100}}]); "
        f"print(e.pk)"
    ))


def _mk_dummy_creditor_settlement(debtor_email: str, dummy_pk: int, value: str = "25.00",
                                   approved: bool = True, group_pk: int = None) -> int:
    group_clause = (
        f"from buddies.models import BuddyGroup; grp=BuddyGroup.objects.get(pk={group_pk}); "
        if group_pk else ""
    )
    group_arg = "buddy_group=grp, " if group_pk else ""
    return int(_shell(
        f"from budget.expense_factory import create_expense; "
        f"from feusers.models import FeUser; from budget.models import TransactionType; "
        f"from decimal import Decimal; import datetime; "
        f"{group_clause}"
        f"a=FeUser.objects.get(email='{debtor_email}'); "
        f"e=create_expense(owning_feuser=a, title='DummyCreditorSettlement', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  date_due=datetime.date.today(), settled=True, notify=False, "
        f"  is_buddies_settlement=True, buddy_approved={'True' if approved else 'False'}, "
        f"  {group_arg}"
        f"  buddy_spendings=[{{'type':'dummy','id':{dummy_pk},'share_percent':100}}]); "
        f"print(e.pk)"
    ))


def _mk_dummy_debtor_settlement(owner_email: str, dummy_pk: int, value: str = "25.00") -> int:
    """Settlement FROM an offline buddy TO the real user (is_dummy=True, no spendings)."""
    return int(_shell(
        f"from budget.expense_factory import create_expense; "
        f"from feusers.models import FeUser; from budget.models import TransactionType; "
        f"from buddies.models import DummyUser; "
        f"from decimal import Decimal; import datetime; "
        f"a=FeUser.objects.get(email='{owner_email}'); "
        f"d=DummyUser.objects.get(pk={dummy_pk}); "
        f"e=create_expense(owning_feuser=a, title='DummyDebtorSettlement', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  date_due=datetime.date.today(), settled=True, notify=False, "
        f"  is_buddies_settlement=True, buddy_approved=True, "
        f"  is_dummy=True, upfront_payee_dummy=d, buddy_spendings=[]); "
        f"print(e.pk)"
    ))


def _mk_personal_dummy(owner_email: str, name: str = "Offline Friend") -> int:
    return int(_shell(
        f"from buddies.models import DummyUser; from feusers.models import FeUser; "
        f"u=FeUser.objects.get(email='{owner_email}'); "
        f"d=DummyUser.objects.create(owning_feuser=u, display_name='{name}'); "
        f"print(d.pk)"
    ))


def _mk_group_dummy(group_pk: int, name: str = "Offline Member") -> int:
    return int(_shell(
        f"from buddies.models import DummyUser, BuddyGroup, BuddyGroupMember; "
        f"g=BuddyGroup.objects.get(pk={group_pk}); "
        f"d=DummyUser.objects.create(owning_group=g, display_name='{name}'); "
        f"BuddyGroupMember.objects.create(group=g, dummy=d); "
        f"print(d.pk)"
    ))


def _expense_exists(ctx_user: dict, pk: int) -> bool:
    resp = api_get("/api/v1/expenses/", ctx_user)
    return any(e["id"] == pk for e in resp.json().get("expenses", []))


# ============================================================================
# G1: Group - edit button for unapproved real-user settlement
# ============================================================================

class TestGroupUnapprovedRealUserSettlementEditable:
    """[G1] The debtor's edit button must appear for unapproved real-user settlements
    in the group view, and the edit page must open without redirect."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="G1Debtor", last_name="A")
        b = setup_user(None, None, first_name="G1Creditor", last_name="B")
        grp_pk = int(_create_group(a["email"], "G1Group"))
        _add_group_member(grp_pk, b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = _mk_feuser_settlement(a["email"], b_pk, value="40.00",
                                        approved=False, group_pk=grp_pk)
        yield {"a": a, "b": b, "grp_pk": grp_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_edit_button_present_in_group_pending_section(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.page_source, \
            "[G1] Edit button must appear for unapproved real-user settlement in group pending section"

    def test_edit_page_opens_without_redirect(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.current_url, \
            "[G1] Edit page must not redirect to expense list for unapproved real-user settlement"


# ============================================================================
# G2: Group - cancellation email on unapproved settlement deletion
# ============================================================================

class TestGroupUnapprovedSettlementDeletionEmail:
    """[G2] Deleting an unapproved real-user group settlement must notify the creditor."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="G2Debtor", last_name="A")
        b = setup_user(None, None, first_name="G2Creditor", last_name="B")
        grp_pk = int(_create_group(a["email"], "G2Group"))
        _add_group_member(grp_pk, b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = _mk_feuser_settlement(a["email"], b_pk, value="35.00",
                                        approved=False, group_pk=grp_pk)
        yield {"a": a, "b": b, "grp_pk": grp_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_delete_button_present(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/" in driver.page_source, \
            "[G2] Delete button must appear for unapproved real-user settlement in group view"

    def test_delete_sends_cancellation_email(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)

    def test_settlement_deleted(self, driver, w, ctx):
        assert not _expense_exists(ctx["a"], ctx["exp_pk"]), \
            "[G2] Settlement must be deleted"

    def test_creditor_receives_cancellation_email(self, driver, w, ctx):
        body = fetch_email(ctx["b"]["email"], "cancelled",
                           ignore_ids=ctx.get("seen_before"))
        assert "G2Debtor" in body, \
            "[G2] Cancellation email must name the debtor"


# ============================================================================
# D1: Direct - settlement to offline buddy must be editable
# ============================================================================

class TestDirectDummyCreditorSettlementEditable:
    """[D1] A settlement where the creditor is an offline buddy must be editable."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="D1Debtor", last_name="A")
        dummy_pk = _mk_personal_dummy(a["email"], "D1Offline")
        exp_pk = _mk_dummy_creditor_settlement(a["email"], dummy_pk, value="20.00",
                                                approved=True)
        yield {"a": a, "dummy_pk": dummy_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])

    def test_edit_button_present_in_buddy_summary(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.page_source, \
            "[D1] Edit button must appear in buddy summary for dummy-creditor settlement"

    def test_edit_page_opens_without_redirect(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.current_url, \
            "[D1] Edit page must not redirect for dummy-creditor settlement"


# ============================================================================
# D2 + D5: Direct - deletion must redirect back to /buddies/ not /budget/expenses/
# ============================================================================

class TestDirectSettlementDeleteRedirect:
    """[D2][D5] After deleting a settlement from the buddy summary, user must land on /buddies/."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="D2Debtor", last_name="A")
        b = setup_user(None, None, first_name="D2Creditor", last_name="B")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        dummy_pk = _mk_personal_dummy(a["email"], "D2Offline")
        # Unapproved settlement to real user (D5 case)
        real_exp_pk = _mk_feuser_settlement(a["email"], b_pk, value="15.00", approved=False)
        # Approved settlement to offline buddy (D2 case)
        dummy_exp_pk = _mk_dummy_creditor_settlement(a["email"], dummy_pk, value="15.00",
                                                      approved=True)
        yield {"a": a, "b": b, "real_exp_pk": real_exp_pk, "dummy_exp_pk": dummy_exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_delete_dummy_settlement_stays_on_buddies_page(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        # Click the delete button for the dummy settlement (it has a back param pointing to /buddies/)
        delete_action = f"/budget/expenses/{ctx['dummy_exp_pk']}/delete/"
        assert delete_action in driver.page_source, \
            "[D2] Delete button must appear for dummy-creditor settlement in buddy summary"
        driver.execute_script(
            f"var f=document.querySelector('form[action=\"{delete_action}\"]');"
            f"if(f)f.submit();"
        )
        time.sleep(2)
        assert "/buddies/summary/" in driver.current_url, \
            "[D2] After deleting from buddy summary, must stay on /buddies/ not /budget/expenses/"

    def test_delete_real_user_settlement_stays_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        delete_action = f"/budget/expenses/{ctx['real_exp_pk']}/delete/"
        assert delete_action in driver.page_source, \
            "[D5] Delete button must appear for unapproved real-user settlement in buddy summary"
        driver.execute_script(
            f"var f=document.querySelector('form[action=\"{delete_action}\"]');"
            f"if(f)f.submit();"
        )
        time.sleep(2)
        assert "/buddies/summary/" in driver.current_url, \
            "[D5] After deleting from buddy summary, must stay on /buddies/ not /budget/expenses/"


# ============================================================================
# D3: Direct - settlement FROM offline buddy TO real user must be editable + deletable
# ============================================================================

class TestDirectDummyDebtorSettlementModifiable:
    """[D3] A settlement where the offline buddy is the payer (is_dummy=True) must be
    both editable and deletable by the real-user owner."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="D3Owner", last_name="A")
        dummy_pk = _mk_personal_dummy(a["email"], "D3Payer")
        exp_pk = _mk_dummy_debtor_settlement(a["email"], dummy_pk, value="18.00")
        yield {"a": a, "dummy_pk": dummy_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])

    def test_edit_button_present_in_buddy_summary(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.page_source, \
            "[D3] Edit button must appear for dummy-debtor settlement in buddy summary"

    def test_delete_button_present_in_buddy_summary(self, driver, w, ctx):
        assert f"/budget/expenses/{ctx['exp_pk']}/delete/" in driver.page_source, \
            "[D3] Delete button must appear for dummy-debtor settlement in buddy summary"

    def test_edit_page_opens_without_redirect(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.current_url, \
            "[D3] Edit page must not redirect for dummy-debtor settlement"

    def test_delete_actually_works(self, driver, w, ctx):
        """Verify deletion of dummy-debtor settlement from the buddy summary."""
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        delete_action = f"/budget/expenses/{ctx['exp_pk']}/delete/"
        driver.execute_script(
            f"var f=document.querySelector('form[action=\"{delete_action}\"]');"
            f"if(f)f.submit();"
        )
        time.sleep(2)
        # Expense should no longer appear in buddy summary
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/delete/" not in driver.page_source, \
            "[D3] Dummy-debtor settlement must be deletable from buddy summary"


# ============================================================================
# D4: Direct - unapproved settlement to real user must be editable
# ============================================================================

class TestDirectUnapprovedRealUserSettlementEditable:
    """[D4] A debtor must be able to edit an unapproved settlement to a real user."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="D4Debtor", last_name="A")
        b = setup_user(None, None, first_name="D4Creditor", last_name="B")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        # Give A a debt to B so the settlement makes sense
        a_pk = int(_get_pk(a["email"]))
        _create_personal_expense_with_buddy(
            owner_email=b["email"], participant_pk=a_pk,
            title="D4Debt", value="80.00", share="50.0", approved=True,
        )
        exp_pk = _mk_feuser_settlement(a["email"], b_pk, value="40.00", approved=False)
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_edit_button_present_in_buddy_summary(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.page_source, \
            "[D4] Edit button must appear in buddy summary for unapproved real-user settlement"

    def test_edit_page_opens_without_redirect(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.current_url, \
            "[D4] Edit page must not redirect for unapproved real-user settlement"

    def test_edit_sends_notification_email_to_creditor(self, driver, w, ctx):
        """Saving an edit to an unapproved settlement notifies the creditor."""
        seen_before = mailpit_seen_ids()
        # Submit the edit form unchanged (just save it)
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        driver.execute_script(
            "document.querySelector('.form-wrap button[type=submit]').click();"
        )
        time.sleep(2)
        body = fetch_email(ctx["b"]["email"], "updated",
                           ignore_ids=seen_before)
        assert "D4Debtor" in body or "settlement" in body.lower(), \
            "[D4] Creditor must receive a notification email when their settlement is edited"


# ============================================================================
# U1 + U2: Buddy summary settle form - offline buddy labels
# ============================================================================

class TestBuddySummaryDropdownLabels:
    """[U1][U2] The settle form dropdowns on /buddies/ must label offline buddies
    as '(offline buddy)', not '(offline member)' or unlabelled."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="ULabel", last_name="A")
        b = setup_user(None, None, first_name="ULabel", last_name="B")
        _create_buddy_link(a["email"], b["email"])
        dummy_pk = _mk_personal_dummy(a["email"], "OfflinePal")
        # Give A a debt to both B and dummy so the settle form appears with both
        a_pk = int(_get_pk(a["email"]))
        _create_personal_expense_with_buddy(
            owner_email=b["email"], participant_pk=a_pk,
            title="ULabelDebt", value="60.00", share="50.0", approved=True,
        )
        # Give dummy a debt to A (so dummy appears in settle form)
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from buddies.models import DummyUser, BuddySpending; "
            f"from decimal import Decimal; import datetime; "
            f"a=FeUser.objects.get(email='{a['email']}'); "
            f"d=DummyUser.objects.get(pk={dummy_pk}); "
            f"e=create_expense(owning_feuser=a, title='UDummyExp', "
            f"  type=TransactionType.EXPENSE, value=Decimal('40.00'), "
            f"  date_due=datetime.date.today(), settled=False, buddy_approved=True, "
            f"  is_dummy=True, upfront_payee_dummy=d, "
            f"  buddy_spendings=[{{'type':'dummy','id':{dummy_pk},'share_percent':100}}]); "
            f"print(e.pk)"
        )
        yield {"a": a, "b": b, "dummy_pk": dummy_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def _get_creditor_option_texts(self, driver) -> list:
        return driver.execute_script(
            "var sel=document.getElementById('direct-settle-creditor');"
            "if(!sel)return [];"
            "return Array.from(sel.options).map(function(o){return o.textContent;});"
        )

    def _get_debtor_option_texts(self, driver) -> list:
        return driver.execute_script(
            "var sel=document.getElementById('direct-settle-debtor-select');"
            "if(!sel)return [];"
            "return Array.from(sel.options).map(function(o){return o.textContent;});"
        )

    def test_creditor_dropdown_labels_offline_buddy(self, driver, w, ctx):
        """[U1] The 'Pay to' dropdown must say '(offline buddy)' for offline buddies."""
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        opts = self._get_creditor_option_texts(driver)
        offline_opts = [o for o in opts if "OfflinePal" in o]
        assert offline_opts, "[U1] OfflinePal must appear in creditor dropdown"
        assert all("offline buddy" in o.lower() for o in offline_opts), \
            f"[U1] Offline buddy in creditor dropdown must say '(offline buddy)', got: {offline_opts}"

    def test_creditor_dropdown_does_not_say_offline_member(self, driver, w, ctx):
        """[U1] Creditor dropdown must not use '(offline member)'."""
        opts = self._get_creditor_option_texts(driver)
        bad = [o for o in opts if "offline member" in o.lower()]
        assert not bad, f"[U1] Creditor dropdown must not say '(offline member)', got: {bad}"

    def test_debtor_dropdown_labels_offline_buddy(self, driver, w, ctx):
        """[U2] The 'Who's paying' dropdown must say '(offline buddy)' for offline buddies."""
        opts = self._get_debtor_option_texts(driver)
        offline_opts = [o for o in opts if "OfflinePal" in o]
        assert offline_opts, "[U2] OfflinePal must appear in debtor (who pays) dropdown"
        assert all("offline buddy" in o.lower() for o in offline_opts), \
            f"[U2] Offline buddy in debtor dropdown must say '(offline buddy)', got: {offline_opts}"

    def test_debtor_dropdown_does_not_say_offline_member(self, driver, w, ctx):
        """[U2] Debtor dropdown must not use '(offline member)'."""
        opts = self._get_debtor_option_texts(driver)
        bad = [o for o in opts if "offline member" in o.lower()]
        assert not bad, f"[U2] Debtor dropdown must not say '(offline member)', got: {bad}"


# ============================================================================
# G3: Group admin can edit unapproved settlement FROM offline member TO real user
# ============================================================================

def _mk_group_dummy_debtor_settlement(admin_email: str, dummy_pk: int, creditor_pk: int,
                                       group_pk: int, value: str = "30.00") -> int:
    """Settlement from a group dummy (debtor) to a real user (creditor). Unapproved."""
    return int(_shell(
        f"from budget.expense_factory import create_expense; "
        f"from feusers.models import FeUser; from budget.models import TransactionType; "
        f"from buddies.models import DummyUser, BuddyGroup; "
        f"from decimal import Decimal; import datetime; "
        f"admin=FeUser.objects.get(email='{admin_email}'); "
        f"d=DummyUser.objects.get(pk={dummy_pk}); "
        f"g=BuddyGroup.objects.get(pk={group_pk}); "
        f"e=create_expense(owning_feuser=admin, title='DummyDebtorGroupSettlement', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  date_due=datetime.date.today(), settled=True, notify=False, "
        f"  is_buddies_settlement=True, buddy_approved=False, "
        f"  is_dummy=True, upfront_payee_dummy=d, buddy_group=g, "
        f"  buddy_spendings=[{{'type':'feuser','id':{creditor_pk},'share_percent':100}}]); "
        f"print(e.pk)"
    ))


class TestGroupAdminDummyDebtorSettlementEditable:
    """[G3] Admin must be able to edit and delete an unapproved settlement FROM an offline
    group member TO a real user, with correct debtor name in notification emails."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="G3Admin", last_name="A")
        creditor = setup_user(None, None, first_name="G3Creditor", last_name="B")
        grp_pk = int(_create_group(admin["email"], "G3Group"))
        _add_group_member(grp_pk, creditor["email"])
        creditor_pk = int(_get_pk(creditor["email"]))
        dummy_pk = _mk_group_dummy(grp_pk, "G3Offline")
        exp_pk = _mk_group_dummy_debtor_settlement(
            admin["email"], dummy_pk, creditor_pk, grp_pk, value="28.00"
        )
        yield {
            "admin": admin, "creditor": creditor,
            "grp_pk": grp_pk, "dummy_pk": dummy_pk, "exp_pk": exp_pk,
        }
        cleanup_user(admin["email"])
        cleanup_user(creditor["email"])

    def test_edit_button_present_in_group_view(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.page_source, \
            "[G3] Edit button must appear for admin on dummy-debtor unapproved group settlement"

    def test_edit_page_opens_without_redirect(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.current_url, \
            "[G3] Edit page must not redirect for dummy-debtor group settlement"

    def test_delete_sends_email_naming_offline_member_not_admin(self, driver, w, ctx):
        """[G4] Cancellation email must name the offline member, not the admin."""
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)

    def test_settlement_is_deleted(self, driver, w, ctx):
        assert not _expense_exists(ctx["admin"], ctx["exp_pk"]), \
            "[G3] Settlement must be deleted after admin removes it"

    def test_cancellation_email_names_offline_member(self, driver, w, ctx):
        """[G4] Email must say 'G3Offline cancelled', not 'G3Admin cancelled'."""
        body = fetch_email(ctx["creditor"]["email"], "cancelled",
                           ignore_ids=ctx.get("seen_before"))
        assert "G3Offline" in body, \
            "[G4] Cancellation email must name the offline member ('G3Offline'), not the admin"
        assert "G3Admin" not in body, \
            "[G4] Cancellation email must NOT name the admin as the debtor"


# ============================================================================
# G5: Group admin can edit settlement FROM offline member TO offline member
# ============================================================================

def _mk_group_dummy_to_dummy_settlement(admin_email: str, debtor_dummy_pk: int,
                                         creditor_dummy_pk: int, group_pk: int,
                                         value: str = "20.00") -> int:
    """Settlement from one group dummy to another. Auto-approved."""
    return int(_shell(
        f"from budget.expense_factory import create_expense; "
        f"from feusers.models import FeUser; from budget.models import TransactionType; "
        f"from buddies.models import DummyUser, BuddyGroup; "
        f"from decimal import Decimal; import datetime; "
        f"admin=FeUser.objects.get(email='{admin_email}'); "
        f"d_debtor=DummyUser.objects.get(pk={debtor_dummy_pk}); "
        f"g=BuddyGroup.objects.get(pk={group_pk}); "
        f"e=create_expense(owning_feuser=admin, title='DummyToDummySettlement', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  date_due=datetime.date.today(), settled=True, notify=False, "
        f"  is_buddies_settlement=True, buddy_approved=True, "
        f"  is_dummy=True, upfront_payee_dummy=d_debtor, buddy_group=g, "
        f"  buddy_spendings=[{{'type':'dummy','id':{creditor_dummy_pk},'share_percent':100}}]); "
        f"print(e.pk)"
    ))


class TestGroupAdminDummyToDummySettlementAlwaysModifiable:
    """[G5] Admin can edit and delete a dummy-to-dummy settlement at any time."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="G5Admin", last_name="A")
        grp_pk = int(_create_group(admin["email"], "G5Group"))
        debtor_dummy_pk = _mk_group_dummy(grp_pk, "G5Debtor")
        creditor_dummy_pk = _mk_group_dummy(grp_pk, "G5Creditor")
        exp_pk = _mk_group_dummy_to_dummy_settlement(
            admin["email"], debtor_dummy_pk, creditor_dummy_pk, grp_pk, value="22.00"
        )
        yield {
            "admin": admin, "grp_pk": grp_pk, "exp_pk": exp_pk,
        }
        cleanup_user(admin["email"])

    def test_edit_button_present_for_dummy_to_dummy_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.page_source, \
            "[G5] Edit button must appear for admin on dummy-to-dummy settlement"

    def test_delete_button_present_for_dummy_to_dummy_settlement(self, driver, w, ctx):
        assert f"/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/" in driver.page_source, \
            "[G5] Delete button must appear for admin on dummy-to-dummy settlement"

    def test_edit_page_opens_without_redirect(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.current_url, \
            "[G5] Edit page must not redirect for dummy-to-dummy settlement"

    def test_delete_actually_works(self, driver, w, ctx):
        """[G5] Admin can actually delete a dummy-to-dummy settlement."""
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        assert not _expense_exists(ctx["admin"], ctx["exp_pk"]), \
            "[G5] Admin must be able to delete a dummy-to-dummy settlement"


# ============================================================================
# D3b: Direct dummy-debtor settlement - actual deletion works
# ============================================================================

class TestDirectDummyDebtorSettlementActualDeletion:
    """[D3] Dummy-debtor personal settlement can actually be deleted."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="D3bOwner", last_name="A")
        dummy_pk = _mk_personal_dummy(a["email"], "D3bPayer")
        exp_pk = _mk_dummy_debtor_settlement(a["email"], dummy_pk, value="12.00")
        yield {"a": a, "exp_pk": exp_pk}
        cleanup_user(a["email"])

    def test_delete_dummy_debtor_settlement_succeeds(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        delete_action = f"/budget/expenses/{ctx['exp_pk']}/delete/"
        assert delete_action in driver.page_source, \
            "[D3] Delete button must appear for dummy-debtor personal settlement"
        driver.execute_script(
            f"var f=document.querySelector('form[action=\"{delete_action}\"]');"
            f"if(f)f.submit();"
        )
        time.sleep(2)
        assert not _expense_exists(ctx["a"], ctx["exp_pk"]), \
            "[D3] Dummy-debtor personal settlement must be deletable"


# ============================================================================
# Approved direct real-user settlement: edit blocked in UI and at endpoint
# ============================================================================

class TestApprovedDirectRealUserSettlementEditBlocked:
    """Can NOT edit an approved real-user settlement: no button in buddy summary,
    and direct URL access redirects away."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="ApprEdit", last_name="A")
        b = setup_user(None, None, first_name="ApprEdit", last_name="B")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = _mk_feuser_settlement(a["email"], b_pk, value="33.00", approved=True)
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_edit_button_absent_in_buddy_summary(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" not in driver.page_source, \
            "Edit button must not appear for approved real-user settlement in buddy summary"

    def test_edit_url_redirects_away(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" not in driver.current_url, \
            "Edit URL must redirect away for approved real-user settlement"

    def test_forged_edit_post_is_rejected(self, driver, w, ctx):
        """[E1] A crafted POST to the edit endpoint must not save changes."""
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/budget/expenses/{ctx['exp_pk']}/edit/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"var ti=document.createElement('input');ti.name='title';ti.value='HACKED';f.appendChild(ti);"
            f"var ty=document.createElement('input');ty.name='type';ty.value='expense';f.appendChild(ty);"
            f"var v=document.createElement('input');v.name='value';v.value='99.99';f.appendChild(v);"
            f"var d=document.createElement('input');d.name='date_due';"
            f"var today=new Date();d.value=today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0')+'-'+String(today.getDate()).padStart(2,'0');"
            f"f.appendChild(d);document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        title = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['exp_pk']}).title)"
        ).strip()
        assert title != "HACKED", \
            "[E1] Forged edit POST must not modify an approved direct real-user settlement"

    def test_delete_button_absent_in_buddy_summary(self, driver, w, ctx):
        """[E2] Delete button must not appear for an approved real-user settlement."""
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/delete/" not in driver.page_source, \
            "[E2] Delete button must not appear for approved real-user settlement in buddy summary"

    def test_direct_delete_post_is_rejected(self, driver, w, ctx):
        """[E2] A crafted POST to the delete endpoint must not remove the expense."""
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/budget/expenses/{ctx['exp_pk']}/delete/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        assert _expense_exists(ctx["a"], ctx["exp_pk"]), \
            "[E2] Approved direct real-user settlement must not be deletable via direct POST"


# ============================================================================
# G11: notification when admin EDITS a dummy-debtor group settlement
# ============================================================================

class TestGroupAdminEditDummyDebtorSettlementNotification:
    """[G11] Admin editing an unapproved dummy-debtor group settlement must notify
    the real-user creditor, naming the offline member as the debtor."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="G11Admin", last_name="A")
        creditor = setup_user(None, None, first_name="G11Creditor", last_name="B")
        grp_pk = int(_create_group(admin["email"], "G11Group"))
        _add_group_member(grp_pk, creditor["email"])
        creditor_pk = int(_get_pk(creditor["email"]))
        dummy_pk = _mk_group_dummy(grp_pk, "G11Offline")
        exp_pk = _mk_group_dummy_debtor_settlement(
            admin["email"], dummy_pk, creditor_pk, grp_pk, value="19.00"
        )
        yield {"admin": admin, "creditor": creditor, "grp_pk": grp_pk, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(creditor["email"])

    def test_edit_sends_update_notification_naming_offline_member(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        driver.execute_script(
            "document.querySelector('.form-wrap button[type=submit]').click();"
        )
        time.sleep(2)
        body = fetch_email(ctx["creditor"]["email"], "updated", ignore_ids=seen_before)
        assert "G11Offline" in body, \
            "[G11] Update email must name the offline member, not the admin"
        assert "G11Admin" not in body, \
            "[G11] Update email must NOT name the admin as debtor"


# ============================================================================
# G13 + G14: Admin CANNOT edit or delete approved dummy-debtor-to-feuser settlement
# ============================================================================

class TestGroupAdminCannotModifyApprovedDummyDebtorSettlement:
    """[G13][G14] Once a real-user creditor approves a dummy-debtor group settlement,
    the admin must not be able to edit or delete it."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="G13Admin", last_name="A")
        creditor = setup_user(None, None, first_name="G13Creditor", last_name="B")
        grp_pk = int(_create_group(admin["email"], "G13Group"))
        _add_group_member(grp_pk, creditor["email"])
        creditor_pk = int(_get_pk(creditor["email"]))
        dummy_pk = _mk_group_dummy(grp_pk, "G13Offline")
        # Approved (creditor confirmed)
        exp_pk = _mk_group_dummy_debtor_settlement(
            admin["email"], dummy_pk, creditor_pk, grp_pk, value="17.00"
        )
        # Force-approve it
        _shell(
            f"from budget.models import Expense; "
            f"Expense.objects.filter(pk={exp_pk}).update(buddy_approved=True)"
        )
        yield {"admin": admin, "creditor": creditor, "grp_pk": grp_pk, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(creditor["email"])

    def test_edit_button_absent_in_group_view(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" not in driver.page_source, \
            "[G13] Edit button must not appear for approved dummy-debtor settlement in group view"

    def test_edit_url_redirects_away(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" not in driver.current_url, \
            "[G13] Edit URL must redirect away for approved dummy-debtor settlement"

    def test_delete_button_absent_in_group_view(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/" not in driver.page_source, \
            "[G14] Delete button must not appear for approved dummy-debtor settlement in group view"

    def test_direct_delete_post_is_rejected(self, driver, w, ctx):
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        # _expense_exists queries the API which filters out is_dummy=True expenses, so use a
        # direct DB check instead.
        still_exists = _shell(
            f"from budget.models import Expense; "
            f"print('yes' if Expense.objects.filter(pk={ctx['exp_pk']}).exists() else 'no')"
        ).strip() == "yes"
        assert still_exists, \
            "[G14] Approved dummy-debtor settlement must not be deletable"

    def test_forged_edit_post_is_rejected(self, driver, w, ctx):
        """[E5] A crafted POST to the edit endpoint must not save changes for an
        approved dummy-debtor group settlement."""
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(1)
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/budget/expenses/{ctx['exp_pk']}/edit/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"var ti=document.createElement('input');ti.name='title';ti.value='HACKED';f.appendChild(ti);"
            f"var ty=document.createElement('input');ty.name='type';ty.value='expense';f.appendChild(ty);"
            f"var v=document.createElement('input');v.name='value';v.value='99.99';f.appendChild(v);"
            f"var d=document.createElement('input');d.name='date_due';"
            f"var today=new Date();d.value=today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0')+'-'+String(today.getDate()).padStart(2,'0');"
            f"f.appendChild(d);document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        # is_dummy=True expenses are invisible to the API, so check via shell
        title = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['exp_pk']}).title)"
        ).strip()
        assert title != "HACKED", \
            "[E5] Forged edit POST must not modify an approved dummy-debtor group settlement"


# ============================================================================
# G15: notification when real member EDITS their own unapproved group settlement
# ============================================================================

class TestGroupRealMemberEditNotification:
    """[G15] Real member editing their own unapproved group settlement must notify the creditor."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="G15Debtor", last_name="A")
        b = setup_user(None, None, first_name="G15Creditor", last_name="B")
        grp_pk = int(_create_group(a["email"], "G15Group"))
        _add_group_member(grp_pk, b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = _mk_feuser_settlement(a["email"], b_pk, value="21.00",
                                        approved=False, group_pk=grp_pk)
        yield {"a": a, "b": b, "grp_pk": grp_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_edit_sends_update_notification_to_creditor(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        driver.execute_script(
            "document.querySelector('.form-wrap button[type=submit]').click();"
        )
        time.sleep(2)
        body = fetch_email(ctx["b"]["email"], "updated", ignore_ids=seen_before)
        assert "G15Debtor" in body, \
            "[G15] Update email must name the debtor when real member edits their group settlement"


# ============================================================================
# G17: endpoint blocks real member editing their own approved group settlement
# ============================================================================

class TestGroupApprovedSettlementEditEndpointBlocked:
    """[G17] Direct URL access to edit an approved group settlement must redirect away."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="G17Debtor", last_name="A")
        b = setup_user(None, None, first_name="G17Creditor", last_name="B")
        grp_pk = int(_create_group(a["email"], "G17Group"))
        _add_group_member(grp_pk, b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = _mk_feuser_settlement(a["email"], b_pk, value="44.00",
                                        approved=True, group_pk=grp_pk)
        yield {"a": a, "b": b, "grp_pk": grp_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_edit_url_redirects_away_for_approved_group_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" not in driver.current_url, \
            "[G17] Edit URL must redirect away for approved real-user group settlement"

    def test_forged_edit_post_is_rejected(self, driver, w, ctx):
        """[E3] A crafted POST to the edit endpoint must not save changes for an
        approved group real-user settlement."""
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(1)
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/budget/expenses/{ctx['exp_pk']}/edit/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"var ti=document.createElement('input');ti.name='title';ti.value='HACKED';f.appendChild(ti);"
            f"var ty=document.createElement('input');ty.name='type';ty.value='expense';f.appendChild(ty);"
            f"var v=document.createElement('input');v.name='value';v.value='99.99';f.appendChild(v);"
            f"var d=document.createElement('input');d.name='date_due';"
            f"var today=new Date();d.value=today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0')+'-'+String(today.getDate()).padStart(2,'0');"
            f"f.appendChild(d);document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        title = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['exp_pk']}).title)"
        ).strip()
        assert title != "HACKED", \
            "[E3] Forged edit POST must not modify an approved group real-user settlement"

    def test_delete_button_absent_in_group_view(self, driver, w, ctx):
        """[E4] Delete button must not appear in group view for an approved real-user settlement."""
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/" not in driver.page_source, \
            "[E4] Delete button must not appear for approved real-user group settlement in group view"

    def test_direct_group_delete_post_is_rejected(self, driver, w, ctx):
        """[E4] A crafted POST to the group delete endpoint must not remove the expense."""
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        assert _expense_exists(ctx["a"], ctx["exp_pk"]), \
            "[E4] Approved real-user group settlement must not be deletable via direct POST"


# ============================================================================
# G18 + G19: non-admin debtor cannot edit/delete approved settlement to group dummy
# ============================================================================

class TestGroupNonAdminDebtorCannotModifyApprovedDummyCreditorSettlement:
    """[G18][G19] Once a group-dummy-creditor settlement is approved, the non-admin
    debtor must not be able to edit or delete it, neither via the UI nor by forging
    requests directly.

    Root cause: _settlement_locked() only checks for feuser creditors; dummy
    creditors leave settlement_can_edit/settlement_can_delete True, so the
    personal edit and delete endpoints allow the request through even though the
    group view correctly hides the buttons.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="G18Admin", last_name="A")
        debtor = setup_user(None, None, first_name="G18Debtor", last_name="B")
        grp_pk = int(_create_group(admin["email"], "G18Group"))
        _add_group_member(grp_pk, debtor["email"])
        dummy_pk = _mk_group_dummy(grp_pk, "G18Offline")
        exp_pk = _mk_dummy_creditor_settlement(
            debtor["email"], dummy_pk, value="30.00", approved=True, group_pk=grp_pk
        )
        yield {"admin": admin, "debtor": debtor, "grp_pk": grp_pk, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(debtor["email"])

    def test_edit_button_absent_in_group_view(self, driver, w, ctx):
        """[G18] The group view must not offer an edit link to the non-admin debtor."""
        _login_as(driver, ctx["debtor"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" not in driver.page_source, \
            "[G18] Edit button must not appear for non-admin debtor in group view"

    def test_edit_url_redirects_away(self, driver, w, ctx):
        """[G18] Directly navigating to the edit URL must redirect away."""
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" not in driver.current_url, \
            "[G18] Edit URL must redirect away for non-admin debtor on approved dummy-creditor group settlement"

    def test_forged_edit_post_is_rejected(self, driver, w, ctx):
        """[G18] A crafted POST to the edit endpoint must not save changes."""
        _login_as(driver, ctx["debtor"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(1)
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/budget/expenses/{ctx['exp_pk']}/edit/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"var ti=document.createElement('input');ti.name='title';ti.value='HACKED';f.appendChild(ti);"
            f"var ty=document.createElement('input');ty.name='type';ty.value='expense';f.appendChild(ty);"
            f"var v=document.createElement('input');v.name='value';v.value='99.99';f.appendChild(v);"
            f"var d=document.createElement('input');d.name='date_due';"
            f"var today=new Date();d.value=today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0')+'-'+String(today.getDate()).padStart(2,'0');"
            f"f.appendChild(d);document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        title = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['exp_pk']}).title)"
        ).strip()
        assert title != "HACKED", \
            "[G18] Forged edit POST must not modify an approved dummy-creditor group settlement"

    def test_delete_button_absent_in_group_view(self, driver, w, ctx):
        """[G19] The group view must not offer a delete link to the non-admin debtor."""
        _login_as(driver, ctx["debtor"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/" not in driver.page_source, \
            "[G19] Delete button must not appear for non-admin debtor in group view"

    def test_forged_personal_delete_post_is_rejected(self, driver, w, ctx):
        """[G19] A crafted POST to the personal delete endpoint must not remove the expense."""
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/budget/expenses/{ctx['exp_pk']}/delete/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        assert _expense_exists(ctx["debtor"], ctx["exp_pk"]), \
            "[G19] Approved dummy-creditor group settlement must not be deletable via personal delete endpoint"

    def test_forged_group_delete_post_is_rejected(self, driver, w, ctx):
        """[G19] A crafted POST to the group delete endpoint must not remove the expense."""
        _login_as(driver, ctx["debtor"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(1)
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        assert _expense_exists(ctx["debtor"], ctx["exp_pk"]), \
            "[G19] Approved dummy-creditor group settlement must not be deletable via group delete endpoint"

    # --- Admin perspective: same settlement, admin should also be blocked ---

    def test_admin_edit_button_absent_in_group_view(self, driver, w, ctx):
        """[G18] Admin must not see an edit button for another member's approved dummy-creditor settlement."""
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" not in driver.page_source, \
            "[G18] Edit button must not appear for admin on another member's approved dummy-creditor settlement"

    def test_admin_delete_button_absent_in_group_view(self, driver, w, ctx):
        """[G19] Admin must not see a delete button for another member's approved dummy-creditor settlement."""
        assert f"/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/" not in driver.page_source, \
            "[G19] Delete button must not appear for admin on another member's approved dummy-creditor settlement"

    def test_admin_forged_group_delete_post_is_rejected(self, driver, w, ctx):
        """[G19] Admin crafting a group delete POST must not remove another member's approved settlement."""
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/buddies/groups/{ctx['grp_pk']}/expense/{ctx['exp_pk']}/delete/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"var t=document.createElement('input');t.name='csrfmiddlewaretoken';t.value=csrf;f.appendChild(t);"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        assert _expense_exists(ctx["debtor"], ctx["exp_pk"]), \
            "[G19] Admin must not be able to delete another member's approved dummy-creditor group settlement"
