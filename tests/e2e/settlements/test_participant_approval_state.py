"""
Participant approval state for buddy expenses.

Covers approve and reject for both direct buddy expenses and project expenses,
plus the 24-hour lock mechanism.
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
    _create_group, _add_group_member, _create_group_expense,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_approval_state(expense_pk, participant_email):
    return _shell(
        f"from buddies.models import BuddySpending; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{participant_email}'); "
        f"bs = BuddySpending.objects.get(expense_id={expense_pk}, participant_feuser=u); "
        f"print(bs.approval_state)"
    ).strip()


def _set_approval_state(expense_pk, participant_email, state):
    _shell(
        f"from buddies.models import BuddySpending; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{participant_email}'); "
        f"BuddySpending.objects.filter(expense_id={expense_pk}, participant_feuser=u)"
        f".update(approval_state={state})"
    )


def _send_participant_notice(expense_pk, actor_email):
    """Trigger the participant notification email for an expense (bypasses form flow)."""
    _shell(
        f"from buddies.services import BuddyEmailService; "
        f"from budget.models import Expense; from feusers.models import FeUser; "
        f"actor = FeUser.objects.get(email='{actor_email}'); "
        f"exp = Expense.objects.get(pk={expense_pk}); "
        f"BuddyEmailService.notify_expense_created(exp, actor)"
    )


def _approve_via_url(driver, expense_pk):
    """Use the direct GET endpoint to approve (simulates email link click)."""
    driver.get(_url(f"/buddies/expense/{expense_pk}/participant-approve/"))
    time.sleep(1)


def _reject_via_url(driver, expense_pk):
    """Use the direct GET endpoint to reject (simulates email link click)."""
    driver.get(_url(f"/buddies/expense/{expense_pk}/participant-reject/"))
    time.sleep(1)


def _get_consent_set_at(expense_pk, participant_email):
    return _shell(
        f"from buddies.models import BuddySpending; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{participant_email}'); "
        f"bs = BuddySpending.objects.get(expense_id={expense_pk}, participant_feuser=u); "
        f"print(bs.consent_set_at)"
    ).strip()


def _set_consent_set_at(expense_pk, participant_email, hours_ago):
    _shell(
        f"from buddies.models import BuddySpending; from feusers.models import FeUser; "
        f"from django.utils import timezone; from datetime import timedelta; "
        f"u = FeUser.objects.get(email='{participant_email}'); "
        f"BuddySpending.objects.filter(expense_id={expense_pk}, participant_feuser=u)"
        f".update(consent_set_at=timezone.now() - timedelta(hours={hours_ago}))"
    )


# ---------------------------------------------------------------------------
# Participation email has Approve / Reject links
# ---------------------------------------------------------------------------

class TestParticipationEmailHasApproveRejectLinks:
    """When B is added as participant, their notice email contains Approve and Reject links."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Alice", last_name="Payer")
        b = setup_user(None, None, first_name="Bob", last_name="Participant")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        seen_before = mailpit_seen_ids()
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk, title="Email Links Expense",
        ))
        _send_participant_notice(exp_pk, a["email"])
        yield {"a": a, "b": b, "exp_pk": exp_pk, "seen_before": seen_before}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_email_has_approve_and_reject_links(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"],
            "included you in a shared expense",
            ignore_ids=ctx["seen_before"],
        )
        assert "participant-approve" in body, \
            "Email must contain a link to participant-approve endpoint"
        assert "participant-reject" in body, \
            "Email must contain a link to participant-reject endpoint"
        assert "Approve" in body
        assert "Reject" in body


# ---------------------------------------------------------------------------
# Direct buddy expense: approve flow
# ---------------------------------------------------------------------------

class TestDirectExpenseParticipantApprove:
    """B approves a direct expense: state=1, payer gets notification, approved badge shows."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Clara", last_name="Payer")
        b = setup_user(None, None, first_name="Dan", last_name="Approver")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk,
            title="Direct Approve Expense", value="80.00",
        ))
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_initial_state_is_neutral(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "0"

    def test_consent_buttons_visible_for_participant(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        btns = driver.find_elements(By.CSS_SELECTOR, "button.btn-consent")
        assert len(btns) > 0, "Consent buttons must be visible for the participant"

    def test_b_approves_via_url(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_approve"] = seen_before
        _approve_via_url(driver, ctx["exp_pk"])

    def test_state_is_approved(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "1"

    def test_payer_receives_approved_notification(self, driver, w, ctx):
        body = fetch_email(
            ctx["a"]["email"],
            "approved a shared expense",
            ignore_ids=ctx["seen_before_approve"],
        )
        assert "Dan Approver" in body
        assert "Direct Approve Expense" in body

    def test_approved_badge_visible_on_payer_summary(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".approval-badge--approved")) > 0


# ---------------------------------------------------------------------------
# Direct buddy expense: reject flow
# ---------------------------------------------------------------------------

class TestDirectExpenseParticipantReject:
    """B rejects a direct expense: state=2, payer gets notification, rejected badge shows."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Eva", last_name="Payer")
        b = setup_user(None, None, first_name="Frank", last_name="Rejecter")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk,
            title="Direct Reject Expense", value="60.00",
        ))
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_initial_state_is_neutral(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "0"

    def test_b_rejects_via_url(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_reject"] = seen_before
        _login_as(driver, ctx["b"])
        _reject_via_url(driver, ctx["exp_pk"])

    def test_state_is_rejected(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "2"

    def test_payer_receives_rejected_notification(self, driver, w, ctx):
        body = fetch_email(
            ctx["a"]["email"],
            "rejected a shared expense",
            ignore_ids=ctx["seen_before_reject"],
        )
        assert "Frank Rejecter" in body
        assert "Direct Reject Expense" in body

    def test_rejected_badge_visible_on_payer_summary(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".approval-badge--rejected")) > 0


# ---------------------------------------------------------------------------
# Project expense: approve flow
# ---------------------------------------------------------------------------

class TestProjectExpenseParticipantApprove:
    """B approves a project expense: state=1, consent buttons on project page, payer notified."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Grace", last_name="Admin")
        b = setup_user(None, None, first_name="Hank", last_name="Member")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        group_pk = int(_create_group(a["email"], "Approval Project"))
        _add_group_member(group_pk, b["email"])
        exp_pk = int(_create_group_expense(
            admin_email=a["email"], participant_email=b["email"],
            group_id=group_pk, title="Project Approve Expense",
            value="120.00", share="50.0",
        ))
        yield {"a": a, "b": b, "exp_pk": exp_pk, "group_pk": group_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_initial_state_is_neutral(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "0"

    def test_consent_buttons_visible_on_project_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/projects/{ctx['group_pk']}/"))
        time.sleep(1)
        btns = driver.find_elements(By.CSS_SELECTOR, "button.btn-consent")
        assert len(btns) > 0, "Consent buttons must appear in the project expense breakdown"

    def test_b_approves_via_url(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_approve"] = seen_before
        _approve_via_url(driver, ctx["exp_pk"])

    def test_state_is_approved(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "1"

    def test_payer_receives_approved_notification(self, driver, w, ctx):
        body = fetch_email(
            ctx["a"]["email"],
            "approved a shared expense",
            ignore_ids=ctx["seen_before_approve"],
        )
        assert "Hank Member" in body
        assert "Project Approve Expense" in body

    def test_approved_badge_on_project_page(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/projects/{ctx['group_pk']}/"))
        time.sleep(1)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".approval-badge--approved")) > 0


# ---------------------------------------------------------------------------
# Project expense: reject flow
# ---------------------------------------------------------------------------

class TestProjectExpenseParticipantReject:
    """B rejects a project expense: state=2, payer notified, rejected badge shows."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Iris", last_name="Admin")
        b = setup_user(None, None, first_name="Jack", last_name="Member")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        group_pk = int(_create_group(a["email"], "Reject Project"))
        _add_group_member(group_pk, b["email"])
        exp_pk = int(_create_group_expense(
            admin_email=a["email"], participant_email=b["email"],
            group_id=group_pk, title="Project Reject Expense",
            value="100.00", share="50.0",
        ))
        yield {"a": a, "b": b, "exp_pk": exp_pk, "group_pk": group_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_initial_state_is_neutral(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "0"

    def test_b_rejects_via_url(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_reject"] = seen_before
        _login_as(driver, ctx["b"])
        _reject_via_url(driver, ctx["exp_pk"])

    def test_state_is_rejected(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "2"

    def test_payer_receives_rejected_notification(self, driver, w, ctx):
        body = fetch_email(
            ctx["a"]["email"],
            "rejected a shared expense",
            ignore_ids=ctx["seen_before_reject"],
        )
        assert "Jack Member" in body
        assert "Project Reject Expense" in body

    def test_rejected_badge_on_project_page(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/projects/{ctx['group_pk']}/"))
        time.sleep(1)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".approval-badge--rejected")) > 0


# ---------------------------------------------------------------------------
# Avatar badges: neutral / approved / rejected CSS classes
# ---------------------------------------------------------------------------

class TestAvatarApprovalBadges:
    """Avatar stack shows the correct badge CSS class for each approval state."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Karl", last_name="Payer")
        b = setup_user(None, None, first_name="Laura", last_name="BadgeUser")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk, title="Badge Test Expense",
        ))
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_neutral_badge_for_state_0(self, driver, w, ctx):
        _set_approval_state(ctx["exp_pk"], ctx["b"]["email"], 0)
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".approval-badge--neutral")) > 0

    def test_approved_badge_for_state_1(self, driver, w, ctx):
        _set_approval_state(ctx["exp_pk"], ctx["b"]["email"], 1)
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".approval-badge--approved")) > 0

    def test_rejected_badge_for_state_2(self, driver, w, ctx):
        _set_approval_state(ctx["exp_pk"], ctx["b"]["email"], 2)
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert len(driver.find_elements(By.CSS_SELECTOR, ".approval-badge--rejected")) > 0


# ---------------------------------------------------------------------------
# Owner cannot use participant endpoints (no BuddySpending row)
# ---------------------------------------------------------------------------

class TestOwnerCannotAccessParticipantEndpoints:
    """The expense owner has no BuddySpending row, so participant-approve returns 404."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Mia", last_name="Owner")
        b = setup_user(None, None, first_name="Nick", last_name="Participant")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk, title="Access Control Expense",
        ))
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_owner_gets_404_on_participant_approve(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/expense/{ctx['exp_pk']}/participant-approve/"))
        time.sleep(1)
        assert "404" in driver.page_source or "Not Found" in driver.page_source, \
            "Owner must get 404 — they have no BuddySpending row for their own expense"


# ---------------------------------------------------------------------------
# 24-hour lock: consent_set_at tracks the latest approval and resets on re-approve
# ---------------------------------------------------------------------------

class TestConsentSetAtRecorded:
    """consent_set_at is set on approve and reset on every subsequent approve;
    rejecting leaves it unchanged so the original approval timestamp is preserved."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Olivia", last_name="Payer")
        b = setup_user(None, None, first_name="Paul", last_name="Timer")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk, title="Timestamp Expense",
        ))
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_consent_set_at_is_null_before_first_decision(self, driver, w, ctx):
        assert _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"]) == "None"

    def test_consent_set_at_null_after_reject(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        _reject_via_url(driver, ctx["exp_pk"])
        assert _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"]) == "None", \
            "consent_set_at must remain null when only a reject has been made"

    def test_consent_set_at_recorded_on_approve(self, driver, w, ctx):
        _approve_via_url(driver, ctx["exp_pk"])
        ts1 = _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"])
        assert ts1 != "None", "consent_set_at must be set after approving"
        ctx["ts1"] = ts1

    def test_consent_set_at_unchanged_after_reject(self, driver, w, ctx):
        _reject_via_url(driver, ctx["exp_pk"])
        ts = _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"])
        assert ts == ctx["ts1"], "consent_set_at must not change when rejecting"

    def test_consent_set_at_reset_on_re_approve(self, driver, w, ctx):
        _approve_via_url(driver, ctx["exp_pk"])
        ts2 = _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"])
        assert ts2 != "None", "consent_set_at must be set after re-approving"
        assert ts2 != ctx["ts1"], "consent_set_at must be refreshed on every approve"


def _is_403(driver):
    """The participant-approve/reject endpoints return a plain HttpResponseForbidden
    with exactly this body when the 24-hour consent lock blocks the request. Matching
    that exact text (instead of generic substrings like "403" or "locked") avoids false
    positives from unrelated content on a successful, fully-rendered redirect target
    page (e.g. a random CSRF token or primary key that happens to contain "403")."""
    return "Decision is locked after 24 hours." in driver.page_source


def _post_to_endpoint(driver, url):
    """Submit a POST directly via JS — simulates a forged request bypassing hidden buttons."""
    driver.execute_script(f"""
        var f = document.createElement('form');
        f.method = 'POST';
        f.action = '{url}';
        var csrf = document.createElement('input');
        csrf.name = 'csrfmiddlewaretoken';
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        csrf.value = match ? match[1] : '';
        f.appendChild(csrf);
        document.body.appendChild(f);
        f.submit();
    """)
    time.sleep(1)


class TestConsentLockAfter24h:
    """After 24h buttons are hidden and both endpoints (approve + reject) deny all requests."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Quinn", last_name="Payer")
        b = setup_user(None, None, first_name="Rita", last_name="Locked")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk, title="Lock Test Expense",
        ))
        _set_approval_state(exp_pk, b["email"], 1)
        _set_consent_set_at(exp_pk, b["email"], hours_ago=25)
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_consent_buttons_hidden_after_lock(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert len(driver.find_elements(By.CSS_SELECTOR, "button.btn-consent")) == 0, \
            "Consent buttons must not be rendered after the 24-hour lock"

    def test_approve_endpoint_get_returns_403(self, driver, w, ctx):
        driver.get(_url(f"/buddies/expense/{ctx['exp_pk']}/participant-approve/"))
        time.sleep(1)
        assert _is_403(driver), "GET to approve endpoint must return 403 after lock"

    def test_reject_endpoint_get_returns_403(self, driver, w, ctx):
        driver.get(_url(f"/buddies/expense/{ctx['exp_pk']}/participant-reject/"))
        time.sleep(1)
        assert _is_403(driver), "GET to reject endpoint must return 403 after lock"

    def test_approve_endpoint_forged_post_returns_403(self, driver, w, ctx):
        # Navigate to a page first so we have a valid session + CSRF cookie.
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        _post_to_endpoint(driver, f"/buddies/expense/{ctx['exp_pk']}/participant-approve/")
        assert _is_403(driver), "Forged POST to approve must return 403 after lock"

    def test_reject_endpoint_forged_post_returns_403(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        _post_to_endpoint(driver, f"/buddies/expense/{ctx['exp_pk']}/participant-reject/")
        assert _is_403(driver), "Forged POST to reject must return 403 after lock"

    def test_state_unchanged_after_all_blocked_requests(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "1", \
            "State must remain 1 (approved) after all blocked requests"


class TestRejectedStateBypassesLock:
    """A rejected direct-buddy decision is always changeable, even after 25 h."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Vera", last_name="Payer")
        b = setup_user(None, None, first_name="Walt", last_name="Rejector")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk, title="Rejected Bypass Expense",
        ))
        _set_approval_state(exp_pk, b["email"], 2)
        _set_consent_set_at(exp_pk, b["email"], hours_ago=25)
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_consent_buttons_still_visible_when_rejected(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        btns = driver.find_elements(By.CSS_SELECTOR, "button.btn-consent")
        assert len(btns) > 0, \
            "Consent buttons must remain visible when state is rejected, regardless of 24-hour window"

    def test_approve_endpoint_succeeds_from_rejected(self, driver, w, ctx):
        _approve_via_url(driver, ctx["exp_pk"])
        assert not _is_403(driver), \
            "Approve endpoint must not return 403 when current state is rejected"

    def test_state_changed_to_approved(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "1", \
            "State must have changed to approved (1) after approve from rejected state"


class TestProjectRejectedStateBypassesLock:
    """A rejected project-expense decision is always changeable, even after 25 h."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Xena", last_name="Admin")
        b = setup_user(None, None, first_name="Yuri", last_name="Rejector")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        group_pk = int(_create_group(a["email"], "Rejected Bypass Project"))
        _add_group_member(group_pk, b["email"])
        exp_pk = int(_create_group_expense(
            admin_email=a["email"], participant_email=b["email"],
            group_id=group_pk, title="Project Rejected Bypass Expense",
            value="80.00", share="50.0",
        ))
        _set_approval_state(exp_pk, b["email"], 2)
        _set_consent_set_at(exp_pk, b["email"], hours_ago=25)
        yield {"a": a, "b": b, "exp_pk": exp_pk, "group_pk": group_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_consent_buttons_still_visible_on_project_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/projects/{ctx['group_pk']}/"))
        time.sleep(1)
        btns = driver.find_elements(By.CSS_SELECTOR, "button.btn-consent")
        assert len(btns) > 0, \
            "Consent buttons must remain visible on project page when state is rejected, regardless of 24-hour window"

    def test_approve_endpoint_succeeds_from_rejected(self, driver, w, ctx):
        _approve_via_url(driver, ctx["exp_pk"])
        assert not _is_403(driver), \
            "Approve endpoint must not return 403 for project expense when current state is rejected"

    def test_state_changed_to_approved(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "1", \
            "State must have changed to approved (1) after approve from rejected state on project expense"


class TestConsentStillUnlockedWithin24h:
    """Within the 24-hour window changes are still allowed."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Sam", last_name="Payer")
        b = setup_user(None, None, first_name="Tina", last_name="Unlocked")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk, title="Still Unlocked Expense",
        ))
        _set_approval_state(exp_pk, b["email"], 1)
        _set_consent_set_at(exp_pk, b["email"], hours_ago=23)
        yield {"a": a, "b": b, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_buttons_still_visible_within_24h(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        btns = driver.find_elements(By.CSS_SELECTOR, "button.btn-consent")
        assert len(btns) > 0, "Consent buttons must still be visible within 24 hours"

    def test_can_change_state_within_24h(self, driver, w, ctx):
        _reject_via_url(driver, ctx["exp_pk"])
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "2", \
            "State change must succeed within the 24-hour window"
