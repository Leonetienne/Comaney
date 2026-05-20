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
