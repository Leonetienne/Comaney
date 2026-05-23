"""
Notification emails triggered by the "Update expenses" endpoint.

When a scheduled expense's fields are applied to generated expenses, the same
notification logic that fires during manual expense edits must also fire here:

  1. Adding a feuser participant  → that feuser gets "added you to a shared expense"
  2. Removing a feuser participant → that feuser gets "removed you from a shared expense"
  3. Value/title change for an expense that already has participants
                                 → existing participants get "updated a shared expense"
  4. Project expense participant  → project member gets "added you to a shared expense"
     when the scheduled is updated to include them

Run: pytest tests/e2e/test_scheduled_update_notifications.py -sx
"""
import json
import time

import pytest
import requests

from helpers import (
    _url, setup_user, cleanup_user,
    fetch_email, mailpit_seen_ids, server_today,
)
from bhelpers import _shell, _create_buddy_link, _create_group, _add_group_member, _get_pk


# ---------------------------------------------------------------------------
# Shared session helper
# ---------------------------------------------------------------------------

def _authenticated_session(ctx) -> requests.Session:
    s = requests.Session()
    r = s.get(_url("/login/"))
    csrf = s.cookies.get("csrftoken", "")
    s.post(_url("/login/"), data={
        "csrfmiddlewaretoken": csrf,
        "email": ctx["email"],
        "password": ctx["password"],
    }, allow_redirects=True)
    return s


def _post_update_expenses(session: requests.Session, sched_id, expense_ids: list) -> dict:
    csrf = session.cookies.get("csrftoken", "")
    r = session.post(
        _url(f"/budget/scheduled/{sched_id}/update-expenses/"),
        json={"expense_ids": expense_ids},
        headers={"X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 200, f"Update expenses returned {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("ok"), f"Update expenses response not ok: {data}"
    return data


def _get_generated_ids(sched_id) -> list:
    raw = _shell(
        f"import json; from budget.models import Expense; "
        f"ids = list(Expense.objects.filter(source_scheduled_id={sched_id})"
        f"  .values_list('uid', flat=True)); "
        f"print(json.dumps(ids))"
    )
    return json.loads(raw)


def _create_scheduled_plain(owner_email: str, title: str, value: str = "60.00") -> str:
    """Create a scheduled expense with no buddy assignment; return its pk as string."""
    today = server_today()
    return _shell(
        f"from feusers.models import FeUser; "
        f"from budget.models import ScheduledExpense; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"s = ScheduledExpense.objects.create("
        f"  owning_feuser=u, title='{title}', type='expense', value='{value}',"
        f"  repeat_every_factor=1, repeat_every_unit='months',"
        f"  repeat_base_date='{today}'"
        f"); print(s.pk)"
    )


def _create_scheduled_with_feuser_participant(
    owner_email: str, participant_pk: int, title: str, value: str = "60.00"
) -> str:
    """Create a scheduled expense with a single feuser participant at 50%; return pk."""
    today = server_today()
    spendings = json.dumps([{"type": "feuser", "id": participant_pk, "share_percent": 50}])
    return _shell(
        f"import json; "
        f"from feusers.models import FeUser; "
        f"from budget.models import ScheduledExpense; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"s = ScheduledExpense.objects.create("
        f"  owning_feuser=u, title='{title}', type='expense', value='{value}',"
        f"  repeat_every_factor=1, repeat_every_unit='months',"
        f"  repeat_base_date='{today}',"
        f"  assign_buddy_mode='single', assign_upfront_type='me',"
        f"  assign_spendings_json='{spendings}'"
        f"); print(s.pk)"
    )


def _run_generate(email: str) -> None:
    _shell(
        f"from django.core.management import call_command; "
        f"call_command('generate_scheduled_expenses', user='{email}')"
    )


# ---------------------------------------------------------------------------
# 1. Adding a feuser participant triggers "added you" email
# ---------------------------------------------------------------------------

class TestUpdateExpensesAddParticipantNotification:
    """
    Flow: plain scheduled expense → generate expenses (no participants) →
    update scheduled to add B as participant → call Update expenses →
    B receives "added you to a shared expense" email.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Owen", last_name="Scheduler")
        b = setup_user(None, None, first_name="Pat", last_name="Added")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))

        sched_id = _create_scheduled_plain(a["email"], "UEN Add Test")
        _run_generate(a["email"])
        exp_ids = _get_generated_ids(sched_id)
        assert exp_ids, "No expenses generated for add-participant test"

        yield {"a": a, "b": b, "b_pk": b_pk, "sched_id": sched_id, "exp_ids": exp_ids}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_add_participant_to_scheduled_and_apply(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before

        spendings = json.dumps([{"type": "feuser", "id": ctx["b_pk"], "share_percent": 50}])
        _shell(
            f"import json; "
            f"from budget.models import ScheduledExpense; "
            f"s = ScheduledExpense.objects.get(pk={ctx['sched_id']}); "
            f"s.assign_buddy_mode = 'single'; "
            f"s.assign_upfront_type = 'me'; "
            f"s.assign_spendings_json = '{spendings}'; "
            f"s.save()"
        )

        session = _authenticated_session(ctx["a"])
        result = _post_update_expenses(session, ctx["sched_id"], ctx["exp_ids"])
        assert result["updated"] >= 1
        time.sleep(2)

    def test_b_receives_added_to_expense_email(self, ctx):
        body = fetch_email(
            ctx["b"]["email"], "added you to a shared expense",
            ignore_ids=ctx["seen_before"],
        )
        assert "UEN Add Test" in body, "Email must mention the expense title"
        assert "Owen Scheduler" in body, "Email must mention the actor's name"

    def test_owner_does_not_receive_self_notification(self, ctx):
        import requests as _req
        from helpers import MAILPIT_API
        msgs = _req.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
        new_for_a = [
            m for m in msgs
            if m["ID"] not in ctx["seen_before"]
            and any(t.get("Address") == ctx["a"]["email"] for t in m.get("To", []))
            and "added you" in m.get("Subject", "").lower()
        ]
        assert new_for_a == [], "Owner must not receive a self-notification"


# ---------------------------------------------------------------------------
# 2. Removing a feuser participant triggers "removed" email
# ---------------------------------------------------------------------------

class TestUpdateExpensesRemoveParticipantNotification:
    """
    Flow: scheduled expense with B as participant → generate expenses →
    update scheduled to remove assignment → call Update expenses →
    B receives "removed you from a shared expense" email.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Quinn", last_name="Remover")
        b = setup_user(None, None, first_name="Rachel", last_name="Removed")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))

        sched_id = _create_scheduled_with_feuser_participant(
            a["email"], b_pk, "UEN Remove Test"
        )
        _run_generate(a["email"])
        exp_ids = _get_generated_ids(sched_id)
        assert exp_ids, "No expenses generated for remove-participant test"

        yield {"a": a, "b": b, "b_pk": b_pk, "sched_id": sched_id, "exp_ids": exp_ids}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_remove_assignment_from_scheduled_and_apply(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before

        _shell(
            f"from budget.models import ScheduledExpense; "
            f"s = ScheduledExpense.objects.get(pk={ctx['sched_id']}); "
            f"s.assign_buddy_mode = ''; "
            f"s.assign_upfront_type = 'me'; "
            f"s.assign_spendings_json = '[]'; "
            f"s.save()"
        )

        session = _authenticated_session(ctx["a"])
        result = _post_update_expenses(session, ctx["sched_id"], ctx["exp_ids"])
        assert result["updated"] >= 1
        time.sleep(2)

    def test_b_receives_removed_from_expense_email(self, ctx):
        body = fetch_email(
            ctx["b"]["email"], "removed you from a shared expense",
            ignore_ids=ctx["seen_before"],
        )
        assert "UEN Remove Test" in body, "Email must mention the expense title"
        assert "Quinn Remover" in body, "Email must mention the actor's name"


# ---------------------------------------------------------------------------
# 3. Value change notifies existing participants
# ---------------------------------------------------------------------------

class TestUpdateExpensesValueChangeNotification:
    """
    Flow: scheduled expense with B as participant → generate expenses →
    update scheduled value → call Update expenses →
    B receives "updated a shared expense" email showing the value changed.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Sam", last_name="Updater")
        b = setup_user(None, None, first_name="Tina", last_name="Notified")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))

        sched_id = _create_scheduled_with_feuser_participant(
            a["email"], b_pk, "UEN Value Test", value="40.00"
        )
        _run_generate(a["email"])
        exp_ids = _get_generated_ids(sched_id)
        assert exp_ids, "No expenses generated for value-change test"

        yield {"a": a, "b": b, "b_pk": b_pk, "sched_id": sched_id, "exp_ids": exp_ids}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_update_scheduled_value_and_apply(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before

        spendings = json.dumps([{"type": "feuser", "id": ctx["b_pk"], "share_percent": 50}])
        _shell(
            f"import json; "
            f"from budget.models import ScheduledExpense; "
            f"s = ScheduledExpense.objects.get(pk={ctx['sched_id']}); "
            f"s.value = '99.00'; "
            f"s.assign_spendings_json = '{spendings}'; "
            f"s.save()"
        )

        session = _authenticated_session(ctx["a"])
        result = _post_update_expenses(session, ctx["sched_id"], ctx["exp_ids"])
        assert result["updated"] >= 1
        time.sleep(2)

    def test_b_receives_updated_expense_email(self, ctx):
        body = fetch_email(
            ctx["b"]["email"], "updated a shared expense",
            ignore_ids=ctx["seen_before"],
        )
        assert "UEN Value Test" in body, "Email must mention the expense title"
        assert "Sam Updater" in body, "Email must mention the actor's name"


# ---------------------------------------------------------------------------
# 4. Project expense: member gets "added you" when participant is added
# ---------------------------------------------------------------------------

class TestUpdateExpensesProjectParticipantNotification:
    """
    Flow: scheduled expense linked to a project with B as member → generate
    plain expenses (no project spendings) → update scheduled to add project
    assignment with B → call Update expenses → B receives "added you" email.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Uma", last_name="ProjectOwner")
        b = setup_user(None, None, first_name="Victor", last_name="Member")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        a_pk = int(_get_pk(a["email"]))

        group_id = _create_group(a["email"], "UEN Project Group")
        _add_group_member(int(group_id), b["email"])

        sched_id = _create_scheduled_plain(a["email"], "UEN Project Test")
        _run_generate(a["email"])
        exp_ids = _get_generated_ids(sched_id)
        assert exp_ids, "No expenses generated for project-participant test"

        yield {
            "a": a, "b": b, "a_pk": a_pk, "b_pk": b_pk,
            "group_id": group_id, "sched_id": sched_id, "exp_ids": exp_ids,
        }
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_add_project_assignment_to_scheduled_and_apply(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before

        spendings = json.dumps([
            {"type": "feuser", "id": ctx["a_pk"], "share_percent": 50},
            {"type": "feuser", "id": ctx["b_pk"], "share_percent": 50},
        ])
        _shell(
            f"import json; "
            f"from budget.models import ScheduledExpense; "
            f"from buddies.models import Project; "
            f"s = ScheduledExpense.objects.get(pk={ctx['sched_id']}); "
            f"p = Project.objects.get(pk={ctx['group_id']}); "
            f"s.assign_buddy_mode = 'group'; "
            f"s.assign_upfront_type = 'me'; "
            f"s.assign_project = p; "
            f"s.assign_spendings_json = '{spendings}'; "
            f"s.save()"
        )

        session = _authenticated_session(ctx["a"])
        result = _post_update_expenses(session, ctx["sched_id"], ctx["exp_ids"])
        assert result["updated"] >= 1
        time.sleep(2)

    def test_b_receives_added_to_project_expense_email(self, ctx):
        body = fetch_email(
            ctx["b"]["email"], "added you to a shared expense",
            ignore_ids=ctx["seen_before"],
        )
        assert "UEN Project Test" in body, "Email must mention the expense title"
        assert "Uma ProjectOwner" in body, "Email must mention the actor's name"
