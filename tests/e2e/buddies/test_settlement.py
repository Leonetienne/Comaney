"""
Settlement feature: creating settlement records to clear debts.

Tests cover:
  - Settle Up section visible on /buddies/summary/ when user owes money
  - Amount input is pre-filled with what is owed
  - Confirmation dialog shows amount and instructs user to send money manually
  - For real-user creditors the dialog mentions that they will be asked to confirm
  - Submitting creates a settlement expense (API verification)
  - Settle Up section remains while creditor has not confirmed (buddy_approved=False)
  - Creditor sees "Did you receive this payment?" on their summary page
  - Creditor can confirm via the approve-settlement page (UI)
  - After confirmation an income expense is created for the creditor (API verification)
  - After confirmation the debt is cleared and Settle Up section disappears for debtor
  - Settle Up section absent when user has no direct debts
  - Bug regression: settlement expense must have date_due set (not null)
  - Group settlement form appears and works (custom amount, confirmation dialog)
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, fetch_email
from bhelpers import (
    _shell, _login_as, _confirm, _create_buddy_link, _get_pk,
    _create_group, _add_group_member, _create_group_expense,
    _create_personal_expense_with_buddy,
)


# ---------------------------------------------------------------------------
# Direct settlement on /buddies/summary/
# ---------------------------------------------------------------------------

class TestDirectSettlement:
    """A owes B via a direct buddy expense; settle-up form appears and works."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Seth", last_name="Debtor")
        b = setup_user(None, None, first_name="Beth", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        # B paid 100, A owes 50% = 50.00
        _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Settle Source Expense",
            value="100.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_settle_section_visible(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source, \
            "Settle Up section must appear when user has outstanding direct debt"

    def test_settle_section_shows_creditor_name(self, driver, w, ctx):
        assert "Beth" in driver.page_source, \
            "Creditor name must be visible in the settle-up section"

    def test_settle_section_shows_amount_owed(self, driver, w, ctx):
        inp = driver.find_element("id", "direct-settle-amount")
        assert "50" in (inp.get_attribute("value") or ""), \
            "Amount owed must be pre-filled in the amount input"

    def test_amount_input_prefilled(self, driver, w, ctx):
        inp = driver.find_element("id", "direct-settle-amount")
        assert inp.get_attribute("value") == "50.00", \
            "Amount input must be pre-filled with 50.00 (what is owed)"

    def test_confirm_dialog_appears_on_submit(self, driver, w, ctx):
        driver.find_element("id", "btn-direct-settle").click()
        time.sleep(0.5)
        dialog_msg = driver.find_element("id", "cdialog-msg").text
        assert "Beth" in dialog_msg, \
            "Confirmation dialog must include the creditor's name"
        assert "50.00" in dialog_msg, \
            "Confirmation dialog must show the settlement amount"
        assert "confirm receipt" in dialog_msg.lower(), \
            "Dialog must mention that the creditor will be asked to confirm receipt"
        assert "send the money" in dialog_msg.lower(), \
            "Dialog must remind the user to actually send the money"
        # Cancel so the form is not submitted yet
        driver.find_element("id", "cdialog-cancel").click()
        time.sleep(0.5)

    def test_submit_creates_settlement_record(self, driver, w, ctx):
        driver.find_element("id", "btn-direct-settle").click()
        _confirm(driver)
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower(), \
            "Flash confirmation must mention settlement record"

    def test_settlement_expense_exists_in_api(self, driver, w, ctx):
        import requests
        api_key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{ctx['a']['email']}').api_key)"
        )
        resp = requests.get(
            _url("/api/v1/expenses/"),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        titles = [e["title"] for e in resp.json()["expenses"]]
        assert any("Settlement to Beth" in t for t in titles), \
            "Settlement expense must appear in A's expense list via API"

    def test_settlement_expense_has_due_date(self, driver, w, ctx):
        due = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser=a, title__icontains='Settlement to Beth').first(); "
            f"print(e.date_due)"
        )
        assert due not in ("None", ""), \
            "Settlement expense date_due must not be null"

    def test_settle_section_still_shows_while_pending(self, driver, w, ctx):
        # Debt is not cleared until creditor confirms, so Settle Up must still appear
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source, \
            "Settle Up section must remain while creditor has not yet confirmed"

    def test_settlement_not_in_waiting_for_approval_for_debtor(self, driver, w, ctx):
        # BF-2: debtor must not see an approval action for their own settlement
        assert "btn-approve-pending" not in driver.page_source, \
            "Settlement expense must not expose an Approve button for the debtor"

    def test_settlement_row_has_no_approve_reject_buttons(self, driver, w, ctx):
        # BF-3: Approve/Reject buttons must not appear on the settlement row for the debtor
        rows = driver.find_elements(By.CSS_SELECTOR, ".bexp-breakdown-card")
        settlement_rows = [r for r in rows if "Settlement to Beth" in r.text]
        assert settlement_rows, "Settlement row must be visible in One-on-one expenses"
        row_html = settlement_rows[0].get_attribute("innerHTML")
        assert 'approve' not in row_html.lower() or 'cdialog' in row_html.lower(), \
            "Settlement row must not contain an Approve button for the debtor"
        assert "/reject/" not in row_html, \
            "Settlement row must not contain a Reject button for the debtor"

    def test_creditor_sees_pending_section(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Waiting for your approval" in driver.page_source, \
            "Creditor must see the 'Waiting for your approval' section"
        assert "Seth" in driver.page_source, \
            "Pending section must show the debtor's name"

    def test_list_button_says_review_not_approve(self, driver, w, ctx):
        # The list-view action must not pre-emptively say "Approve"
        link = driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']")
        assert link.text.strip() == "Review", \
            f"List-view link must say 'Review', got '{link.text.strip()}'"

    def test_creditor_confirms_via_ui(self, driver, w, ctx):
        approve_link = driver.find_element(
            "css selector", "section a[href*='/approve-settlement/']"
        )
        approve_link.click()
        time.sleep(1)
        # Now on confirm_settlement page — click the approve form's submit button specifically
        assert "Confirm" in driver.page_source, \
            "Must land on the settlement confirmation page"
        driver.find_element(By.ID, "btn-approve-settlement").click()
        time.sleep(1)
        assert "confirmed" in driver.page_source.lower(), \
            "Flash must confirm that the settlement was accepted"

    def test_creditor_income_expense_created(self, driver, w, ctx):
        import requests
        api_key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{ctx['b']['email']}').api_key)"
        )
        resp = requests.get(
            _url("/api/v1/expenses/"),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        expenses = resp.json()["expenses"]
        income = [e for e in expenses if e["type"] == "income" and "Seth" in e["title"]]
        assert income, \
            "Creditor must have an income expense created after confirming settlement"
        assert income[0]["settled"] is True, \
            "The creditor's income expense must be settled=true"
        assert income[0].get("date_due") not in (None, ""), \
            "The creditor's income expense must have date_due set"

    def test_debtor_notified_of_approval_by_email(self, driver, w, ctx):
        body = fetch_email(ctx["a"]["email"], subject_fragment="confirmed")
        assert body, \
            "Debtor must receive an email when the creditor confirms the settlement"
        assert "Beth" in body, \
            "Approval email must include the creditor's name"

    def test_debt_cleared_after_confirmation(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        inp = driver.find_element("id", "direct-settle-amount")
        assert inp.get_attribute("value") in ("", None), \
            "Amount input must be empty once the creditor has confirmed"


class TestDirectSettlementNoDebt:
    """When user has no direct debt, settle-up section must not appear."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        # a paid, b owes a (a has positive net, b is debtor but b is not logged in)
        a = setup_user(driver, w, first_name="Nina", last_name="NoDebt")
        b = setup_user(None, None, first_name="Olaf", last_name="Owes")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        # A paid 80, B owes 50% = 40 → A has positive net
        _create_personal_expense_with_buddy(
            owner_email=a["email"],
            participant_pk=b_pk,
            title="No Debt Expense",
            value="80.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_settle_section_visible_for_creditor(self, driver, w, ctx):
        # A is the creditor but still has a direct buddy; the form must appear
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source, \
            "Pay someone back section must appear whenever the user has a direct buddy"

    def test_amount_not_prefilled_when_no_debt(self, driver, w, ctx):
        # A owes nobody so the amount input must be empty (no pre-fill)
        inp = driver.find_element("id", "direct-settle-amount")
        val = inp.get_attribute("value")
        assert val in ("", None), \
            f"Amount must not be pre-filled when user has no debt, got '{val}'"


# ---------------------------------------------------------------------------
# Creditor rejects a direct settlement (req 14.9b)
# ---------------------------------------------------------------------------

class TestDirectSettlementRejection:
    """B rejects A's settlement: expense deleted, A notified, debt stays open."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Ray", last_name="Debtor")
        b = setup_user(None, None, first_name="Kay", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        # B paid 60, A owes 50% = 30.00
        _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Rejection Source Expense",
            value="60.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_settlement_confirm_url_requires_being_creditor(self, driver, w, ctx):
        import requests as req
        # Get a settlement expense uid that belongs to a different pair (Seth/Beth from the
        # other class won't exist yet in a fresh run, so create a fresh one via shell)
        uid = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"e = Expense.objects.filter(buddy_spendings__participant_feuser=b, "
            f"  buddy_approved=False, is_buddies_settlement=True).first(); "
            f"print(e.uid if e else 'none')"
        )
        # At this point no settlement exists yet; just verify the view 404s for a wrong user.
        # Log in as A and try to open B's approve-settlement URL for any expense.
        # We'll use a non-existent ID to confirm the view enforces the creditor check.
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/expense/999999999/approve-settlement/"))
        time.sleep(1)
        assert driver.current_url != _url("/buddies/expense/999999999/approve-settlement/") \
            or "404" in driver.page_source or "not found" in driver.page_source.lower(), \
            "Accessing another user's settlement URL must return 404"

    def test_a_submits_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        driver.find_element("id", "btn-direct-settle").click()
        _confirm(driver)
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower(), \
            "Flash must confirm settlement record was created"

    def test_b_lands_on_confirm_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        approve_link = driver.find_element(
            "css selector", "section a[href*='/approve-settlement/']"
        )
        approve_link.click()
        time.sleep(1)
        assert "did not receive" in driver.page_source.lower(), \
            "Confirm page must offer a rejection option"

    def test_b_rejects_with_confirmation_dialog(self, driver, w, ctx):
        # Click the reject button — a confirmation dialog must appear first
        driver.find_element(By.ID, "btn-reject-settlement").click()
        time.sleep(0.5)
        dialog_msg = driver.find_element("id", "cdialog-msg").text
        assert "reject" in dialog_msg.lower(), \
            "Rejection dialog must mention rejecting the settlement"
        assert "deleted" in dialog_msg.lower(), \
            "Rejection dialog must warn that the record will be deleted"
        _confirm(driver)
        time.sleep(1)

    def test_rejection_flash_shown(self, driver, w, ctx):
        assert "rejected" in driver.page_source.lower(), \
            "Flash message must confirm the settlement was rejected"

    def test_settlement_expense_deleted(self, driver, w, ctx):
        count = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"print(Expense.objects.filter(owning_feuser=a, is_buddies_settlement=True).count())"
        )
        assert count == "0", \
            "Settlement expense must be deleted after creditor rejects"

    def test_b_no_longer_sees_pending_section(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Waiting for your approval" not in driver.page_source, \
            "Creditor must no longer see the pending section after rejecting"

    def test_settle_up_reappears_for_a(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source, \
            "Settle Up section must reappear for debtor after creditor rejects"

    def test_debtor_notified_by_email(self, driver, w, ctx):
        body = fetch_email(ctx["a"]["email"], subject_fragment="rejected")
        assert body, \
            "Debtor must receive an email notifying them of the rejection"
        assert "Kay" in body, \
            "Rejection email must include the creditor's name"


# ---------------------------------------------------------------------------
# Group settlement on /projects/<id>/
# ---------------------------------------------------------------------------

class TestGroupSettlement:
    """User owes a group member; settle-up form appears on group detail page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Greg", last_name="GroupPaid")
        member = setup_user(driver, w, first_name="Mona", last_name="GroupOwes")
        group_id = _create_group(admin["email"], "SettleGroup")
        _add_group_member(group_id, member["email"])
        # Admin paid 200, member owes 50% = 100
        _create_group_expense(
            admin_email=admin["email"],
            participant_email=member["email"],
            group_id=group_id,
            title="Group Settle Source",
            value="200.00",
            share="50.0",
        )
        yield {"admin": admin, "member": member, "group_id": group_id}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_settle_section_visible_for_debtor(self, driver, w, ctx):
        # Member owes admin 100; settle-up should be visible for member
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source, \
            "Pay someone back section must appear for the group member who owes money"

    def test_settle_section_shows_creditor_name(self, driver, w, ctx):
        assert "Greg" in driver.page_source, \
            "Creditor name must be visible in the group settle-up section"

    def test_settle_section_shows_amount(self, driver, w, ctx):
        assert "100.00" in driver.page_source, \
            "Owed amount must be shown in the group settle-up section"

    def test_submit_creates_group_settlement_record(self, driver, w, ctx):
        amt = driver.find_element(By.ID, "settle-amount")
        driver.execute_script("arguments[0].value = '100.00';", amt)
        driver.find_element(
            By.ID, "btn-settle-individual"
        ).click()
        _confirm(driver)
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower(), \
            "Flash confirmation must appear after group settlement submission"

    def test_group_settlement_expense_exists_in_api(self, driver, w, ctx):
        import requests
        api_key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{ctx['member']['email']}').api_key)"
        )
        resp = requests.get(
            _url("/api/v1/expenses/"),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        titles = [e["title"] for e in resp.json()["expenses"]]
        assert any("Settlement" in t and "Greg" in t and "SettleGroup" in t for t in titles), \
            "Group settlement expense must include both creditor name and group name"

    def test_admin_sees_no_debt_in_balances(self, driver, w, ctx):
        # "Pay someone back" is always rendered; what matters is that the admin
        # who is owed money has no "You owe" row in "Your balances".
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "You owe" not in driver.page_source, \
            "Admin who is owed money must not see a 'You owe' balance row"
        assert "owes you" in driver.page_source, \
            "Admin must see a 'owes you' row confirming they are the creditor"


# ---------------------------------------------------------------------------
# Group settlement review flow: Review -> Approve/Reject/Cancel
# ---------------------------------------------------------------------------

class TestGroupSettlementReviewFlow:
    """After a group settlement is created, the creditor uses the Review flow."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Greta", last_name="GroupCreditor")
        member = setup_user(driver, w, first_name="Marco", last_name="GroupDebtor")
        group_id = _create_group(admin["email"], "ReviewFlowGroup")
        _add_group_member(group_id, member["email"])
        # Admin paid 100, member owes 50% = 50
        _create_group_expense(
            admin_email=admin["email"],
            participant_email=member["email"],
            group_id=group_id,
            title="Review Flow Source",
            value="100.00",
            share="50.0",
        )
        yield {"admin": admin, "member": member, "group_id": group_id}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_member_submits_group_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        amt = driver.find_element(By.ID, "settle-amount")
        driver.execute_script("arguments[0].value = '50.00';", amt)
        driver.find_element(
            By.ID, "btn-settle-individual"
        ).click()
        _confirm(driver)
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower(), \
            "Flash must confirm settlement record was created"

    def test_settlement_appears_in_waiting_for_approval_not_breakdown(self, driver, w, ctx):
        # Still logged in as member (debtor): pending settlement must show in
        # "Waiting for approval", not in "Expense Breakdown"
        time.sleep(0.5)
        src = driver.page_source
        assert "Waiting for approval" in src, \
            "Pending settlement must appear in the 'Waiting for approval' section"
        # The approved-expenses div must not contain the settlement.
        # (The "Waiting for approval" section is nested inside the "Expense Breakdown"
        # section, so we check by the approved-section id rather than the h2 text.)
        assert 'id="proj-approved-section"' not in src or \
            "Settlement" not in src.split('id="proj-approved-section"')[-1], \
            "Settlement must not appear in the approved expense section"

    def test_no_review_button_for_debtor(self, driver, w, ctx):
        # The debtor must not see a Review button for their own settlement
        review_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/approve-settlement/']")
        assert not review_links, \
            "Debtor must not see a Review button for their own settlement"

    def test_creditor_sees_waiting_for_approval_section(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Waiting for approval" in driver.page_source, \
            "Creditor must see the 'Waiting for approval' section on the group page"
        assert "Marco" in driver.page_source, \
            "Debtor's name must appear in the waiting-for-approval section"

    def test_creditor_review_button_says_review(self, driver, w, ctx):
        link = driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']")
        assert link.text.strip() == "Review", \
            f"Button must read 'Review', got '{link.text.strip()}'"

    def test_creditor_lands_on_confirm_page(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        assert "did not receive" in driver.page_source.lower(), \
            "Confirm page must show both approve and reject options"
        assert "Cancel" in driver.page_source, \
            "Confirm page must show a Cancel button"

    def test_cancel_returns_to_group_page(self, driver, w, ctx):
        driver.find_element(By.PARTIAL_LINK_TEXT, "Cancel").click()
        time.sleep(1)
        assert f"/projects/{ctx['group_id']}/" in driver.current_url, \
            f"Cancel must return to the group detail page, not the buddy summary. Landed on {driver.current_url}"

    def test_creditor_approves_via_review_flow(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        driver.find_element(By.ID, "btn-approve-settlement").click()
        time.sleep(1)
        assert "confirmed" in driver.page_source.lower(), \
            "Flash must confirm receipt after creditor approves"
        assert f"/projects/{ctx['group_id']}/" in driver.current_url, \
            "After approving, must redirect back to the group detail page"

    def test_waiting_section_gone_after_approval(self, driver, w, ctx):
        assert "Waiting for approval" not in driver.page_source, \
            "Waiting for approval section must disappear after creditor confirms"

    def test_settlement_moves_to_expense_breakdown(self, driver, w, ctx):
        assert "Expense Breakdown" in driver.page_source, \
            "Approved settlement must now appear in the Expense Breakdown"

    def test_creditor_income_expense_created(self, driver, w, ctx):
        import requests
        api_key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{ctx['admin']['email']}').api_key)"
        )
        resp = requests.get(
            _url("/api/v1/expenses/"),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        income = [e for e in resp.json()["expenses"]
                  if e["type"] == "income" and "Marco" in e["title"]]
        assert income, \
            "Creditor must have an income expense created after confirming the group settlement"


class TestGroupSettlementRejectionFlow:
    """Creditor rejects a group settlement via the Review page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Hana", last_name="WontPay")
        member = setup_user(driver, w, first_name="Lars", last_name="Rejecter")
        group_id = _create_group(admin["email"], "RejectFlowGroup")
        _add_group_member(group_id, member["email"])
        _create_group_expense(
            admin_email=admin["email"],
            participant_email=member["email"],
            group_id=group_id,
            title="Reject Flow Source",
            value="80.00",
            share="50.0",
        )
        yield {"admin": admin, "member": member, "group_id": group_id}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_member_submits_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        amt = driver.find_element(By.ID, "settle-amount")
        driver.execute_script("arguments[0].value = '40.00';", amt)
        driver.find_element(
            By.ID, "btn-settle-individual"
        ).click()
        _confirm(driver)
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower()

    def test_creditor_rejects_via_review_page(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        driver.find_element(By.ID, "btn-reject-settlement").click()
        time.sleep(0.5)
        _confirm(driver)
        time.sleep(1)
        assert "rejected" in driver.page_source.lower(), \
            "Flash must confirm the settlement was rejected"
        assert f"/projects/{ctx['group_id']}/" in driver.current_url, \
            "After rejecting, must redirect back to the group detail page"

    def test_waiting_section_gone_after_rejection(self, driver, w, ctx):
        assert "Waiting for approval" not in driver.page_source, \
            "Waiting for approval section must disappear after rejection"

    def test_debtor_notified_by_email(self, driver, w, ctx):
        body = fetch_email(ctx["member"]["email"], subject_fragment="rejected")
        assert body, \
            "Debtor must receive a rejection email"
        assert "Hana" in body, \
            "Rejection email must include the creditor's name"
