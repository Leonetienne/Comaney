"""
Project expense with zero participants: the payer covers the whole cost alone.

Regression: in a multi-member project a user could not remove the last
participant from an expense (the "book a payment only for myself" case). The
form's submit guard wrongly required at least one participant for every buddy
expense, including project expenses where zero participants is valid (the
backend accepts it: the payer simply covers the cost alone).

Covers creating and editing a project expense down to zero participants, and
verifies the semantics for every upfront-payer type: the expense stays in the
project and is attributed solely to the payer (me, another real-account member,
or an offline member/dummy), with no participant rows.

Run just this file:
  pytest tests/e2e/projects/test_project_expense_no_participants.py -v | tee logfile.log
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, api_get, server_today
from bhelpers import _shell, _create_group, _add_group_member, _confirm


def _uncheck_all_participants(driver):
    """Uncheck every participant checkbox (group mode) and fire the change event.

    The checkbox <input> sits inside its <label>, so a real click toggles it
    twice (input + label) and nets no change; we uncheck via JS instead and
    dispatch 'change' so the buddy JS re-syncs its participant list.
    """
    driver.execute_script(
        "document.querySelectorAll("
        "'#buddy-participants-checkboxes .buddy-participant-cb input[type=checkbox]')"
        ".forEach(function (cb) {"
        "  if (cb.checked) {"
        "    cb.checked = false;"
        "    cb.dispatchEvent(new Event('change', {bubbles: true}));"
        "  }"
        "});"
    )
    time.sleep(0.3)


def _submit_form(driver):
    driver.find_element(
        By.CSS_SELECTOR,
        "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)",
    ).click()
    time.sleep(2)


def _participant_count(title):
    """Number of participant BuddySpending rows for the newest expense of `title`."""
    return int(_shell(
        "from budget.models import Expense; "
        "from buddies.models import BuddySpending; "
        f"e = Expense.objects.filter(title='{title}').order_by('-uid').first(); "
        "print(BuddySpending.objects.filter(expense=e).count() if e else -1)"
    ))


def _expense_attr(title, expr):
    """Evaluate `expr` (a Python expression over `e`) for the newest expense of
    `title`, returning its stringified result. `e` is the Expense instance."""
    return _shell(
        "from budget.models import Expense; "
        f"e = Expense.objects.filter(title='{title}').order_by('-uid').first(); "
        f"print({expr} if e else 'NONE')"
    )


def _select_payer(driver, value):
    """Set the upfront payer (e.g. 'feuser:12' or 'dummy:5') and fire change."""
    driver.execute_script(
        "var sel = document.getElementById('buddy-upfront-select');"
        f"sel.value = '{value}';"
        "sel.dispatchEvent(new Event('change', {bubbles: true}));"
    )
    time.sleep(0.4)


class TestCreateProjectExpenseNoParticipants:
    """A multi-member project expense can be saved with no participants at all;
    the payer covers the whole cost alone."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="Nora", last_name="Solo")
        email = user["email"]
        group_id = int(_create_group(email, "Vacation No Participants"))
        # Add a dummy member so the project is NOT solo (multi-member path).
        _shell(
            "from buddies.services import BuddyGroupService; "
            "from feusers.models import FeUser; from buddies.models import Project; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = Project.objects.get(pk={group_id}); "
            "BuddyGroupService.create_group_dummy(g, u, 'Travel Buddy')"
        )
        yield {**user, "group_id": group_id}
        cleanup_user(email)

    def test_create_expense_without_participants(self, driver, w, ctx):
        gid = ctx["group_id"]
        today = server_today()
        driver.get(_url(f"/budget/expenses/new/?project={gid}&back=/projects/{gid}/"))
        time.sleep(1.5)
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("Just For Me")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("42.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        # Remove the last participant (all members are checked by default).
        _uncheck_all_participants(driver)
        _submit_form(driver)

    def test_form_actually_submitted(self, driver, w, ctx):
        # The no-participants guard must NOT have blocked the submit: we left the
        # form. (Blocked submits stay on /budget/expenses/new/.)
        assert "/budget/expenses/new" not in driver.current_url, \
            f"Form was blocked on submit; still on the new-expense page: {driver.current_url}"

    def test_no_participants_error_not_shown(self, driver, w, ctx):
        assert "requires at least one participant" not in driver.page_source, \
            "The no-participants error must not appear for a project expense"

    def test_expense_created_with_zero_participants(self, driver, w, ctx):
        assert _participant_count("Just For Me") == 0, \
            "A zero-participant project expense must have no BuddySpending rows"

    def test_expense_in_owner_api_list(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Just For Me"})
        assert resp.status_code == 200
        assert any(e["title"] == "Just For Me" for e in resp.json()["expenses"]), \
            "The expense must appear in the payer's own expense list"


class TestEditProjectExpenseRemoveLastParticipant:
    """An existing project expense can be edited down to zero participants."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="Owen", last_name="Editor")
        email = user["email"]
        group_id = int(_create_group(email, "Edit Down To Zero"))
        dummy_id = int(_shell(
            "from buddies.services import BuddyGroupService; "
            "from feusers.models import FeUser; from buddies.models import Project; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = Project.objects.get(pk={group_id}); "
            "d = BuddyGroupService.create_group_dummy(g, u, 'Split Buddy'); "
            "print(d.pk)"
        ))
        # Create a project expense that DOES have a participant (the dummy).
        expense_uid = int(_shell(
            "from budget.expense_factory import create_expense; "
            "from budget.models import TransactionType; "
            "from feusers.models import FeUser; "
            "from buddies.models import Project, DummyUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.get(pk={dummy_id}); "
            "e = create_expense(owning_feuser=u, title='Shared Then Solo', "
            "value=100, type=TransactionType.EXPENSE, settled=True, project=g, "
            "buddy_spendings=[{'type':'dummy','id':d.uid,'share_percent':100}]); "
            "print(e.uid)"
        ))
        yield {**user, "group_id": group_id, "dummy_id": dummy_id, "expense_uid": expense_uid}
        cleanup_user(email)

    def test_precondition_has_participant(self, driver, w, ctx):
        assert _participant_count("Shared Then Solo") == 1, \
            "Fixture must start with exactly one participant"

    def test_edit_remove_last_participant(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['expense_uid']}/edit/"))
        time.sleep(1.5)
        _uncheck_all_participants(driver)
        _submit_form(driver)

    def test_edit_submitted(self, driver, w, ctx):
        assert "/edit" not in driver.current_url, \
            f"Edit was blocked on submit; still on the edit page: {driver.current_url}"

    def test_participant_removed(self, driver, w, ctx):
        assert _participant_count("Shared Then Solo") == 0, \
            "Editing away the last participant must leave zero BuddySpending rows"

    def test_reopen_edit_keeps_participants_unchecked(self, driver, w, ctx):
        # Regression: reopening the edit view of a zero-participant project
        # expense must NOT auto-check every project member again.
        driver.get(_url(f"/budget/expenses/{ctx['expense_uid']}/edit/"))
        time.sleep(1.5)
        checked = driver.execute_script(
            "return Array.from(document.querySelectorAll("
            "'#buddy-participants-checkboxes .buddy-participant-cb input[type=checkbox]'))"
            ".filter(function (cb) { return cb.checked; }).length;"
        )
        assert checked == 0, \
            f"Reopening the edit view re-checked {checked} member(s); expected none"


class TestNoParticipantsRealAccountPayer:
    """Zero-participant project expense where a *real account* member is the
    upfront payer. It must stay in the project, carry no participants, and be
    attributed to that member (recorded on their account, pending their
    approval)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        creator = setup_user(driver, w, first_name="Carla", last_name="Creator")
        payer = setup_user(driver, w, first_name="Ralf", last_name="Realpayer")
        email = creator["email"]
        group_id = int(_create_group(email, "Real Payer Project"))
        _add_group_member(group_id, payer["email"])
        payer_pk = int(_shell(
            "from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{payer['email']}').pk)"
        ))
        # Log the creator back in (setup_user leaves the payer session active).
        from bhelpers import _login_as
        _login_as(driver, creator)
        yield {**creator, "group_id": group_id,
               "payer_email": payer["email"], "payer_pk": payer_pk}
        cleanup_user(creator["email"])
        cleanup_user(payer["email"])

    def test_create_with_real_account_payer_no_participants(self, driver, w, ctx):
        gid = ctx["group_id"]
        today = server_today()
        driver.get(_url(f"/budget/expenses/new/?project={gid}&back=/projects/{gid}/"))
        time.sleep(1.5)
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("Ralf Paid Alone")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("30.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        _select_payer(driver, f"feuser:{ctx['payer_pk']}")
        _uncheck_all_participants(driver)
        driver.find_element(
            By.CSS_SELECTOR,
            "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)",
        ).click()
        # A real-account payer triggers a "recorded on their account" confirm.
        _confirm(driver)
        time.sleep(1.5)

    def test_expense_attributed_to_payer(self, driver, w, ctx):
        assert _expense_attr("Ralf Paid Alone", "e.owning_feuser.email") == ctx["payer_email"], \
            "Expense must be recorded on the real-account payer's account"

    def test_expense_stays_in_project(self, driver, w, ctx):
        assert _expense_attr("Ralf Paid Alone", "e.project_id") == str(ctx["group_id"]), \
            "Expense must remain assigned to the project"

    def test_no_participants(self, driver, w, ctx):
        assert _participant_count("Ralf Paid Alone") == 0, \
            "There must be no participant rows (payer covers the cost alone)"

    def test_pending_payer_approval(self, driver, w, ctx):
        assert _expense_attr("Ralf Paid Alone", "e.buddy_approved") == "False", \
            "An expense recorded on another account must await that user's approval"


class TestNoParticipantsOfflineMemberPayer:
    """Zero-participant project expense where an *offline member* (dummy) is the
    upfront payer. It must stay in the project, carry no participants, and be
    attributed to that offline member."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="Dana", last_name="Dummypay")
        email = user["email"]
        group_id = int(_create_group(email, "Offline Payer Project"))
        dummy_id = int(_shell(
            "from buddies.services import BuddyGroupService; "
            "from feusers.models import FeUser; from buddies.models import Project; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = Project.objects.get(pk={group_id}); "
            "d = BuddyGroupService.create_group_dummy(g, u, 'Olga Offline'); "
            "print(d.pk)"
        ))
        yield {**user, "group_id": group_id, "dummy_id": dummy_id}
        cleanup_user(email)

    def test_create_with_offline_payer_no_participants(self, driver, w, ctx):
        gid = ctx["group_id"]
        today = server_today()
        driver.get(_url(f"/budget/expenses/new/?project={gid}&back=/projects/{gid}/"))
        time.sleep(1.5)
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("Olga Paid Alone")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("25.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        _select_payer(driver, f"dummy:{ctx['dummy_id']}")
        _uncheck_all_participants(driver)
        _submit_form(driver)

    def test_expense_attributed_to_offline_member(self, driver, w, ctx):
        # Owned by the creator (dummies have no login), but flagged as paid by the
        # offline member via is_dummy + upfront_payee_dummy.
        assert _expense_attr("Olga Paid Alone", "e.is_dummy") == "True", \
            "Offline-member payment must be flagged is_dummy"
        assert _expense_attr("Olga Paid Alone", "e.upfront_payee_dummy_id") == str(ctx["dummy_id"]), \
            "Expense must point at the offline member as upfront payer"

    def test_expense_stays_in_project(self, driver, w, ctx):
        assert _expense_attr("Olga Paid Alone", "e.project_id") == str(ctx["group_id"]), \
            "Expense must remain assigned to the project"

    def test_no_participants(self, driver, w, ctx):
        assert _participant_count("Olga Paid Alone") == 0, \
            "There must be no participant rows (offline payer covers the cost alone)"

    def test_not_in_creator_expense_list(self, driver, w, ctx):
        # is_dummy expenses never surface in the regular expense list/API.
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Olga Paid Alone"})
        assert resp.status_code == 200
        assert not any(e["title"] == "Olga Paid Alone" for e in resp.json()["expenses"]), \
            "Offline-payer expense must not appear in the creator's regular expense list"
