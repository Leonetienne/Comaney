"""
Owner edits reset participant approvals.

When the expense owner edits a shared expense and changes the title, value,
participants or their shares, every participant's approval decision (the Check /
X consent) is reset: the state goes back to neutral and the last-set date is
cleared. The participant's update email tells them their decision was reset.

Editing only an unrelated field (payee, note, category, date) must NOT reset an
existing approval.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, setup_user, cleanup_user, fetch_email, mailpit_seen_ids, server_today,
)
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk,
    _create_personal_expense_with_buddy,
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


def _get_consent_set_at(expense_pk, participant_email):
    return _shell(
        f"from buddies.models import BuddySpending; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{participant_email}'); "
        f"bs = BuddySpending.objects.get(expense_id={expense_pk}, participant_feuser=u); "
        f"print(bs.consent_set_at)"
    ).strip()


def _mark_approved(expense_pk, participant_email):
    """Simulate the participant having approved via the Check button."""
    _shell(
        f"from buddies.models import BuddySpending; from feusers.models import FeUser; "
        f"from django.utils import timezone; "
        f"u = FeUser.objects.get(email='{participant_email}'); "
        f"BuddySpending.objects.filter(expense_id={expense_pk}, participant_feuser=u)"
        f".update(approval_state=1, consent_set_at=timezone.now())"
    )


def _set_buddy_hidden_inputs(driver, b_pk, share=50):
    """Keep the single-buddy assignment populated when submitting the edit form."""
    driver.execute_script(
        f"document.getElementById('buddy-spendings-json').value = "
        f"JSON.stringify([{{type:'feuser',id:{b_pk},share_percent:{share}}}]);"
        f"document.getElementById('buddy-upfront-type-input').value = 'me';"
        f"document.getElementById('buddy-mode-input').value = 'single';"
    )


def _submit_form(driver):
    driver.find_element(
        By.CSS_SELECTOR,
        "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)"
    ).click()
    time.sleep(2)


# ---------------------------------------------------------------------------
# Value change resets approval
# ---------------------------------------------------------------------------

class TestValueChangeResetsApproval:
    """B has approved; A changes the value; B's approval is reset and B is told."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Anna", last_name="Owner")
        b = setup_user(None, None, first_name="Ben", last_name="Approver")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk,
            title="Reset On Value Expense", value="60.00", share="50.0",
        ))
        _mark_approved(exp_pk, b["email"])
        yield {"a": a, "b": b, "b_pk": b_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_precondition_b_is_approved(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "1"
        assert _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"]) != "None"

    def test_owner_edits_value(self, driver, w, ctx):
        today = server_today()
        ctx["seen_before"] = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        driver.execute_script(
            "document.getElementById('id_value').value = '90.00';"
            f"document.getElementById('id_date_due').value = '{today}';"
        )
        _set_buddy_hidden_inputs(driver, ctx["b_pk"])
        _submit_form(driver)

    def test_approval_state_reset_to_neutral(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "0", \
            "Changing the value must reset the participant's approval to neutral"

    def test_last_set_date_cleared(self, driver, w, ctx):
        assert _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"]) == "None", \
            "Changing the value must clear the approval's last-set date"

    def test_update_email_mentions_reset(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "updated a shared expense",
            ignore_ids=ctx["seen_before"],
        )
        assert "approval has been reset" in body, \
            "Update email must tell the participant their approval was reset"
        assert "participant-approve" in body, \
            "Update email must offer a link to approve again after a reset"


# ---------------------------------------------------------------------------
# Title change resets approval
# ---------------------------------------------------------------------------

class TestTitleChangeResetsApproval:
    """B has approved; A changes only the title; B's approval is still reset."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Cora", last_name="Owner")
        b = setup_user(None, None, first_name="Dirk", last_name="Approver")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk,
            title="Reset On Title Expense", value="40.00", share="50.0",
        ))
        _mark_approved(exp_pk, b["email"])
        yield {"a": a, "b": b, "b_pk": b_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_owner_edits_title(self, driver, w, ctx):
        today = server_today()
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        driver.execute_script(
            "document.getElementById('id_title').value = 'Reset On Title Expense RENAMED';"
            f"document.getElementById('id_date_due').value = '{today}';"
        )
        _set_buddy_hidden_inputs(driver, ctx["b_pk"])
        _submit_form(driver)

    def test_approval_reset(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "0", \
            "Changing the title must reset the participant's approval"
        assert _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"]) == "None"


# ---------------------------------------------------------------------------
# Share change resets approval
# ---------------------------------------------------------------------------

class TestShareChangeResetsApproval:
    """B has approved; A changes B's share; B's approval is reset."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Elsa", last_name="Owner")
        b = setup_user(None, None, first_name="Finn", last_name="Approver")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk,
            title="Reset On Share Expense", value="100.00", share="50.0",
        ))
        _mark_approved(exp_pk, b["email"])
        yield {"a": a, "b": b, "b_pk": b_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_owner_changes_share(self, driver, w, ctx):
        today = server_today()
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
        )
        # Same participant, different share
        _set_buddy_hidden_inputs(driver, ctx["b_pk"], share=70)
        _submit_form(driver)

    def test_approval_reset(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "0", \
            "Changing a participant's share must reset their approval"
        assert _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"]) == "None"


# ---------------------------------------------------------------------------
# No prior approval: update email carries no reset note
# ---------------------------------------------------------------------------

class TestNoPriorApprovalNoResetNote:
    """B never approved; A changes the value. B still gets an update email (the
    value changed), but it must NOT tell them their approval was reset."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Ida", last_name="Owner")
        b = setup_user(None, None, first_name="Jon", last_name="Neutral")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk,
            title="No Prior Approval Expense", value="50.00", share="50.0",
        ))
        # Deliberately leave B's approval neutral (state 0).
        yield {"a": a, "b": b, "b_pk": b_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_precondition_state_neutral(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "0"

    def test_owner_edits_value(self, driver, w, ctx):
        today = server_today()
        ctx["seen_before"] = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        driver.execute_script(
            "document.getElementById('id_value').value = '65.00';"
            f"document.getElementById('id_date_due').value = '{today}';"
        )
        _set_buddy_hidden_inputs(driver, ctx["b_pk"])
        _submit_form(driver)

    def test_update_email_has_no_reset_note(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "updated a shared expense",
            ignore_ids=ctx["seen_before"],
        )
        assert "No Prior Approval Expense" in body, "Sanity: correct update email"
        assert "approval has been reset" not in body, \
            "A participant who never approved must not be told their approval was reset"


# ---------------------------------------------------------------------------
# Unrelated field change preserves approval
# ---------------------------------------------------------------------------

class TestUnrelatedChangePreservesApproval:
    """B has approved; A edits only the payee; B's approval is preserved."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Gwen", last_name="Owner")
        b = setup_user(None, None, first_name="Hugo", last_name="Approver")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk,
            title="Keep Approval Expense", value="80.00", share="50.0",
        ))
        _mark_approved(exp_pk, b["email"])
        yield {"a": a, "b": b, "b_pk": b_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_precondition_consent_timestamp(self, driver, w, ctx):
        ctx["consent_before"] = _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"])
        assert ctx["consent_before"] != "None"

    def test_owner_edits_payee_only(self, driver, w, ctx):
        today = server_today()
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        driver.execute_script(
            "document.getElementById('id_payee').value = 'Some Shop';"
            "document.getElementById('id_title').value = 'Keep Approval Expense';"
            "document.getElementById('id_value').value = '80.00';"
            f"document.getElementById('id_date_due').value = '{today}';"
        )
        _set_buddy_hidden_inputs(driver, ctx["b_pk"])
        _submit_form(driver)

    def test_approval_preserved(self, driver, w, ctx):
        assert _get_approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "1", \
            "Editing only the payee must not reset an existing approval"

    def test_last_set_date_preserved(self, driver, w, ctx):
        assert _get_consent_set_at(ctx["exp_pk"], ctx["b"]["email"]) == ctx["consent_before"], \
            "Editing only the payee must preserve the approval's last-set date"
