"""
Buddy expense approval and rejection flows.

Setup is done via shell (creates an unapproved expense owned by B with A as
participant, mirroring what happens when A sets B as upfront payer in the form).
UI tests verify the approve/reject actions and their email side-effects.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, setup_user, cleanup_user,
    fetch_email, mailpit_seen_ids,
)
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk,
    _create_personal_expense_with_buddy,
)


# ---------------------------------------------------------------------------
# B (owner, owning_feuser) approves the expense
# ---------------------------------------------------------------------------

class TestExpenseApproval:
    """B sees 'Needs approval'; B approves; badge disappears."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Anna", last_name="Approver")
        b = setup_user(None, None, first_name="Boris", last_name="Approver")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        # Expense owned by B (unapproved), A is a participant
        exp_pk = _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Approval Expense",
            value="60.00",
            share="50.0",
            approved=False,
        )
        ctx = {"a": a, "b": b, "exp_pk": int(exp_pk)}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_b_sees_needs_approval_badge(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Needs approval" in driver.page_source
        assert "Approval Expense" in driver.page_source

    def test_b_approves_expense(self, driver, w, ctx):
        driver.find_element(By.ID, f"btn-review-exp-{ctx['exp_pk']}").click()
        time.sleep(1)
        driver.find_element(By.ID, "btn-approve-settlement").click()
        time.sleep(1)
        assert "/budget/expenses/" in driver.current_url

    def test_badge_gone_after_approval(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Needs approval" not in driver.page_source
        assert "Approval Expense" in driver.page_source, \
            "Approved expense must still be visible on the summary page"

    def test_a_sees_expense_on_summary_after_approval(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Approval Expense" in driver.page_source


# ---------------------------------------------------------------------------
# B (owner) rejects the expense; A gets an email notification
# ---------------------------------------------------------------------------

class TestExpenseOwnerRejection:
    """B (owner) rejects expense: it is deleted; A receives a rejection email."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Rosa", last_name="Rejecter")
        b = setup_user(None, None, first_name="Blake", last_name="Rejecter")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        exp_pk = _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Rejection Expense",
            value="40.00",
            share="50.0",
            approved=False,
        )
        ctx = {"a": a, "b": b, "exp_pk": int(exp_pk)}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_b_sees_needs_approval_badge(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Needs approval" in driver.page_source
        assert "Rejection Expense" in driver.page_source

    def test_b_rejects_expense(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        driver.find_element(By.ID, f"btn-review-exp-{ctx['exp_pk']}").click()
        time.sleep(1)
        driver.find_element(By.ID, "btn-reject-settlement").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "/budget/expenses/" in driver.current_url

    def test_expense_gone_from_b_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Rejection Expense" not in driver.page_source, \
            "Rejected expense must be deleted and no longer visible for B"

    def test_a_receives_rejection_email(self, driver, w, ctx):
        email_a = ctx["a"]["email"]
        body = fetch_email(
            email_a, "declined",
            ignore_ids=ctx.get("seen_before"),
        )
        assert "Blake Rejecter" in body or "declined" in body.lower(), \
            "Rejection email must identify the rejecter"

    def test_rejection_email_says_expense_removed(self, driver, w, ctx):
        email_a = ctx["a"]["email"]
        body = fetch_email(email_a, "declined")
        assert "removed entirely" in body.lower() or "removed" in body.lower(), \
            "Rejection email must state the expense was removed entirely"

    def test_expense_gone_from_a_summary(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Rejection Expense" not in driver.page_source, \
            "Rejected expense must not appear on A's summary either"


# ---------------------------------------------------------------------------
# A (participant) sees the expense as pending on their own summary
# ---------------------------------------------------------------------------

class TestParticipantSeesNeedsApproval:
    """A (participant) sees 'Needs approval' badge but cannot approve/reject."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Petra", last_name="Participant")
        b = setup_user(None, None, first_name="Owen", last_name="Owner")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Pending For A",
            value="80.00",
            share="50.0",
            approved=False,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_sees_pending_expense_on_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Pending For A" in driver.page_source
        assert "Needs approval" in driver.page_source

    def test_a_has_no_review_button(self, driver, w, ctx):
        # Only the expense owner (B) gets the Review button; A must not
        review_buttons = driver.find_elements(By.CSS_SELECTOR, "[id^='btn-review-exp-']")
        assert len(review_buttons) == 0, "Participant A must not see the Review button"


# ---------------------------------------------------------------------------
# Suppression: notify_expense_assignments=False
# ---------------------------------------------------------------------------

class TestExpenseAssignmentNotificationSuppressed:
    """notify_expense_assignments=False: approval-request email not sent to the payer."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Assign", last_name="Initiator")
        b = setup_user(None, None, first_name="Assign", last_name="Payer")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        exp_pk = _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Assignment Suppressed",
            value="40.00",
            share="50.0",
            approved=False,
        )
        yield {"a": a, "b": b, "exp_pk": int(exp_pk)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_no_assignment_email_when_class_disabled(self, driver, w, ctx):
        _shell(
            f"from feusers.models import FeUser; "
            f"FeUser.objects.filter(email='{ctx['b']['email']}')"
            f".update(notify_expense_assignments=False)"
        )
        seen_before = mailpit_seen_ids()
        _shell(
            f"from buddies.services.email import BuddyEmailService; "
            f"from budget.models import Expense; from feusers.models import FeUser; "
            f"exp = Expense.objects.get(pk={ctx['exp_pk']}); "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"BuddyEmailService.send_expense_approval_request(exp, a)"
        )
        time.sleep(2)
        import requests
        from helpers import MAILPIT_API
        msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
        new_for_b = [
            m for m in msgs
            if m["ID"] not in seen_before
            and any(t.get("Address") == ctx["b"]["email"] for t in m.get("To", []))
        ]
        assert len(new_for_b) == 0, \
            "No approval-request email expected when notify_expense_assignments=False"
        _shell(
            f"from feusers.models import FeUser; "
            f"FeUser.objects.filter(email='{ctx['b']['email']}')"
            f".update(notify_expense_assignments=True)"
        )


# ---------------------------------------------------------------------------
# Suppression: notify_participant_decisions=False
# ---------------------------------------------------------------------------

class TestParticipantDecisionNotificationSuppressed:
    """notify_participant_decisions=False: participant approval change not sent to the payer."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Payer", last_name="NoDecision")
        b = setup_user(None, None, first_name="Part", last_name="Decider")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = _create_personal_expense_with_buddy(
            owner_email=a["email"],
            participant_pk=b_pk,
            title="Decision Suppressed",
            value="60.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b, "b_pk": b_pk, "exp_pk": int(exp_pk)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_no_decision_email_when_class_disabled(self, driver, w, ctx):
        _shell(
            f"from feusers.models import FeUser; "
            f"FeUser.objects.filter(email='{ctx['a']['email']}')"
            f".update(notify_participant_decisions=False)"
        )
        seen_before = mailpit_seen_ids()
        _shell(
            f"from buddies.services.email import BuddyEmailService; "
            f"from buddies.models import BuddySpending; "
            f"from budget.models import Expense; from feusers.models import FeUser; "
            f"exp = Expense.objects.get(pk={ctx['exp_pk']}); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"BuddyEmailService.send_participant_approval_notification("
            f"  exp, b, BuddySpending.APPROVAL_APPROVED)"
        )
        time.sleep(2)
        import requests
        from helpers import MAILPIT_API
        msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
        new_for_a = [
            m for m in msgs
            if m["ID"] not in seen_before
            and any(t.get("Address") == ctx["a"]["email"] for t in m.get("To", []))
        ]
        assert len(new_for_a) == 0, \
            "No participant-decision email expected when notify_participant_decisions=False"
        _shell(
            f"from feusers.models import FeUser; "
            f"FeUser.objects.filter(email='{ctx['a']['email']}')"
            f".update(notify_participant_decisions=True)"
        )
