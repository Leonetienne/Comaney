"""
Scheduled expense assignment — end-to-end tests.

Scenarios:
  1. UI: create a scheduled expense with project assignment and verify it's saved.
  2. Generation: assignment (project, upfront payer, spendings with correct shares
     and participants) carries through to the generated Expense rows exactly.
  3. Project deleted → assignment resets to none.
  4. Personal offline buddy kicked → assignment resets to none.
  5. User kicked from group (remove_member) → assignment resets to none.
  6. Direct buddy removed via kick_actual → assignment resets to none.

Run: pytest tests/e2e/buddies/test_scheduled_assignment.py -sx
"""
import json
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user, server_today
from bhelpers import _shell, _login_as, _create_group, _add_group_member, _create_buddy_link


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


# ── shell helpers ─────────────────────────────────────────────────────────────

def _run_generate(email: str) -> None:
    _shell(
        f"from django.core.management import call_command; "
        f"call_command('generate_scheduled_expenses', user='{email}')"
    )


def _create_scheduled_with_project(owner_email: str, project_id: int,
                                    member_pks: list[int],
                                    title: str = "Sched Project Test",
                                    share: float = None) -> str:
    """Create a scheduled expense with project assignment; return uid string."""
    n = len(member_pks)
    if share is None:
        share = round(100.0 / n, 4)
    spendings = json.dumps(
        [{"type": "feuser", "id": pk, "share_percent": share} for pk in member_pks]
    )
    return _shell(
        f"import json; "
        f"from feusers.models import FeUser; "
        f"from buddies.models import Project; "
        f"from budget.models import ScheduledExpense; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"p = Project.objects.get(pk={project_id}); "
        f"s = ScheduledExpense.objects.create("
        f"  owning_feuser=u, title='{title}', type='expense', value='60.00',"
        f"  repeat_every_factor=1, repeat_every_unit='months',"
        f"  repeat_base_date='2025-01-01',"
        f"  assign_buddy_mode='group', assign_upfront_type='me',"
        f"  assign_project=p, assign_spendings_json='{spendings}'"
        f"); print(s.pk)"
    )


def _create_scheduled_with_dummy_upfront(owner_email: str, dummy_uid: int,
                                          buddy_participant_uid: int,
                                          title: str = "Sched Dummy") -> str:
    """Create a scheduled expense where an offline buddy pays upfront; return uid."""
    spendings = json.dumps([{"type": "dummy", "id": buddy_participant_uid, "share_percent": 50.0}])
    return _shell(
        f"import json; "
        f"from feusers.models import FeUser; "
        f"from buddies.models import DummyUser; "
        f"from budget.models import ScheduledExpense; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"d = DummyUser.objects.get(uid={dummy_uid}); "
        f"s = ScheduledExpense.objects.create("
        f"  owning_feuser=u, title='{title}', type='expense', value='30.00',"
        f"  repeat_every_factor=1, repeat_every_unit='months',"
        f"  repeat_base_date='2025-01-01',"
        f"  assign_buddy_mode='single', assign_upfront_type='dummy',"
        f"  assign_upfront_dummy=d,"
        f"  assign_spendings_json='{spendings}'"
        f"); print(s.pk)"
    )


def _create_scheduled_with_feuser_participant(owner_email: str, buddy_feuser_pk: int,
                                               title: str = "Sched Feuser Buddy") -> str:
    """Scheduled expense: owner pays, buddy is participant at 50%. Return uid."""
    spendings = json.dumps([{"type": "feuser", "id": buddy_feuser_pk, "share_percent": 50.0}])
    return _shell(
        f"import json; "
        f"from feusers.models import FeUser; "
        f"from budget.models import ScheduledExpense; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"s = ScheduledExpense.objects.create("
        f"  owning_feuser=u, title='{title}', type='expense', value='100.00',"
        f"  repeat_every_factor=1, repeat_every_unit='months',"
        f"  repeat_base_date='2025-01-01',"
        f"  assign_buddy_mode='single', assign_upfront_type='me',"
        f"  assign_spendings_json='{spendings}'"
        f"); print(s.pk)"
    )


def _get_generated_expenses(sched_uid: str) -> list[dict]:
    """Return list of dicts with expense data for all expenses generated from sched_uid."""
    raw = _shell(
        f"import json; "
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending; "
        f"exps = list(Expense.objects.filter(source_scheduled_id={sched_uid})"
        f"  .prefetch_related('buddy_spendings')); "
        f"result = []; "
        f"[result.append({{"
        f"  'project_id': str(e.project_id or ''),"
        f"  'is_dummy': e.is_dummy,"
        f"  'upfront_dummy_id': str(e.upfront_payee_dummy_id or ''),"
        f"  'spendings': [("
        f"    {{'type': 'feuser', 'id': bs.participant_feuser_id, 'share_percent': float(bs.share_percent)}}"
        f"    if bs.participant_feuser_id else "
        f"    {{'type': 'dummy', 'id': bs.participant_dummy_id, 'share_percent': float(bs.share_percent)}}"
        f"  ) for bs in e.buddy_spendings.all()]"
        f"}}) for e in exps]; "
        f"print(json.dumps(result))"
    )
    return json.loads(raw)


def _scheduled_assign_mode(uid: str) -> str:
    return _shell(
        f"from budget.models import ScheduledExpense; "
        f"print(ScheduledExpense.objects.get(pk={uid}).assign_buddy_mode)"
    )


def _scheduled_spendings(uid: str) -> list[dict]:
    raw = _shell(
        f"import json; from budget.models import ScheduledExpense; "
        f"print(ScheduledExpense.objects.get(pk={uid}).assign_spendings_json)"
    )
    return json.loads(raw)


def _create_personal_dummy(owner_email: str, name: str = "Offline Bob") -> str:
    return _shell(
        f"from feusers.models import FeUser; from buddies.models import DummyUser; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"d = DummyUser.objects.create(owning_feuser=u, display_name='{name}'); print(d.uid)"
    )


def _kick_dummy_via_service(owner_email: str, dummy_uid: int) -> None:
    _shell(
        f"from feusers.models import FeUser; from buddies.models import DummyUser; "
        f"from buddies.services import BuddyLifecycleService; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"d = DummyUser.objects.get(uid={dummy_uid}); "
        f"BuddyLifecycleService.kick_dummy(u, d, has_debt_warning_accepted=True)"
    )


def _kick_actual_via_service(kicker_email: str, kicked_email: str) -> None:
    _shell(
        f"from feusers.models import FeUser; "
        f"from buddies.services import BuddyLifecycleService; "
        f"kicker = FeUser.objects.get(email='{kicker_email}'); "
        f"kicked = FeUser.objects.get(email='{kicked_email}'); "
        f"BuddyLifecycleService.kick_actual(kicker, kicked, has_debt_warning_accepted=True)"
    )


def _dissolve_group_via_service(admin_email: str, group_id: int) -> None:
    _shell(
        f"from feusers.models import FeUser; from buddies.models import Project; "
        f"from buddies.services import ProjectService; "
        f"u = FeUser.objects.get(email='{admin_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"ProjectService.dissolve_group(g, u)"
    )


def _remove_member_via_service(admin_email: str, member_email: str, group_id: int) -> None:
    _shell(
        f"from feusers.models import FeUser; "
        f"from buddies.models import Project, ProjectMember; "
        f"from buddies.services import ProjectService; "
        f"admin = FeUser.objects.get(email='{admin_email}'); "
        f"member = FeUser.objects.get(email='{member_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"m = ProjectMember.objects.get(group=g, feuser=member); "
        f"ProjectService.remove_member(g, admin, m)"
    )


def _feuser_pk(email: str) -> int:
    return int(_shell(f"from feusers.models import FeUser; print(FeUser.objects.get(email='{email}').pk)"))


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestScheduledAssignmentForm:
    """Creating a scheduled expense with project assignment via UI."""

    def test_create_with_project_assignment(self, driver, w, ctx):
        ctx2 = setup_user(driver, w)
        _create_buddy_link(ctx["email"], ctx2["email"])
        group_id = _create_group(ctx["email"], "UI Assign Group")
        _add_group_member(int(group_id), ctx2["email"])

        _login_as(driver, ctx)
        today = server_today()
        driver.get(_url("/budget/scheduled/new/"))
        time.sleep(1)

        driver.execute_script("document.getElementById('id_title').value = 'UI Assign Test';")
        driver.execute_script("document.getElementById('id_value').value = '88.00';")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        driver.execute_script("document.getElementById('id_repeat_every_factor').value = '1';")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script(
            f"document.getElementById('id_repeat_base_date').value = '{today}';")

        driver.find_element(By.CSS_SELECTOR, "#assign-tab-group [data-assign='project']").click()
        time.sleep(0.5)
        Select(driver.find_element(By.ID, "buddy-group-select")).select_by_value(group_id)
        time.sleep(0.5)

        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(2)

        saved = _shell(
            "from budget.models import ScheduledExpense; "
            "s = ScheduledExpense.objects.filter(title='UI Assign Test').first(); "
            f"print(s.assign_buddy_mode + '|' + str(s.assign_project_id) if s else 'NONE')"
        )
        mode, proj = saved.split("|")
        assert mode == "group"
        assert proj == group_id

        cleanup_user(ctx2["email"])


class TestScheduledAssignmentGeneratesCorrectly:
    """Generated Expense rows carry exactly the assignment: project, shares, participants."""

    def test_project_assignment_propagates_to_generated_expense(self, driver, w, ctx):
        ctx2 = setup_user(driver, w)
        _create_buddy_link(ctx["email"], ctx2["email"])
        group_id = _create_group(ctx["email"], "Generate Check Group")
        _add_group_member(int(group_id), ctx2["email"])

        owner_pk = _feuser_pk(ctx["email"])
        member_pk = _feuser_pk(ctx2["email"])

        # 70/30 custom split
        spendings = [
            {"type": "feuser", "id": owner_pk, "share_percent": 70.0},
            {"type": "feuser", "id": member_pk, "share_percent": 30.0},
        ]
        sched_uid = _shell(
            f"import json; "
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project; "
            f"from budget.models import ScheduledExpense; "
            f"u = FeUser.objects.get(pk={owner_pk}); "
            f"p = Project.objects.get(pk={group_id}); "
            f"s = ScheduledExpense.objects.create("
            f"  owning_feuser=u, title='Gen Check Project', type='expense', value='100.00',"
            f"  repeat_every_factor=1, repeat_every_unit='months',"
            f"  repeat_base_date='2025-01-01',"
            f"  assign_buddy_mode='group', assign_upfront_type='me',"
            f"  assign_project=p,"
            f"  assign_spendings_json=json.dumps({json.dumps(spendings)})"
            f"); print(s.pk)"
        )

        _run_generate(ctx["email"])
        expenses = _get_generated_expenses(sched_uid)

        assert len(expenses) > 0, "No expenses were generated"

        exp = expenses[0]
        assert exp["project_id"] == group_id, f"project_id mismatch: {exp}"
        assert exp["is_dummy"] is False

        # Check participants and exact share percentages
        by_id = {s["id"]: s for s in exp["spendings"]}
        assert owner_pk in by_id, f"Owner not in spendings: {exp['spendings']}"
        assert member_pk in by_id, f"Member not in spendings: {exp['spendings']}"
        assert abs(by_id[owner_pk]["share_percent"] - 70.0) < 0.01
        assert abs(by_id[member_pk]["share_percent"] - 30.0) < 0.01

        cleanup_user(ctx2["email"])

    def test_dummy_upfront_assignment_propagates_to_generated_expense(self, driver, w, ctx):
        dummy_uid = _create_personal_dummy(ctx["email"], "Gen Dummy Payer")
        owner_pk = _feuser_pk(ctx["email"])

        spendings = json.dumps([{"type": "dummy", "id": int(dummy_uid), "share_percent": 50.0}])
        sched_uid = _shell(
            f"import json; "
            f"from feusers.models import FeUser; "
            f"from buddies.models import DummyUser; "
            f"from budget.models import ScheduledExpense; "
            f"u = FeUser.objects.get(pk={owner_pk}); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"s = ScheduledExpense.objects.create("
            f"  owning_feuser=u, title='Gen Dummy Upfront', type='expense', value='40.00',"
            f"  repeat_every_factor=1, repeat_every_unit='months',"
            f"  repeat_base_date='2025-01-01',"
            f"  assign_buddy_mode='single', assign_upfront_type='dummy',"
            f"  assign_upfront_dummy=d,"
            f"  assign_spendings_json='{spendings}'"
            f"); print(s.pk)"
        )

        _run_generate(ctx["email"])
        expenses = _get_generated_expenses(sched_uid)

        assert len(expenses) > 0
        exp = expenses[0]
        assert exp["is_dummy"] is True
        assert exp["upfront_dummy_id"] == dummy_uid

        # Participant should be the dummy at 50%
        assert len(exp["spendings"]) == 1
        spending = exp["spendings"][0]
        assert spending["type"] == "dummy"
        assert spending["id"] == int(dummy_uid)
        assert abs(spending["share_percent"] - 50.0) < 0.01


class TestScheduledAssignmentProjectDeletion:
    """Dissolving a project resets assignment to none."""

    def test_dissolve_resets_assignment(self, driver, w, ctx):
        group_id = _create_group(ctx["email"], "Dissolve Group")
        owner_pk = _feuser_pk(ctx["email"])
        sched_uid = _create_scheduled_with_project(
            ctx["email"], int(group_id), [owner_pk]
        )

        assert _scheduled_assign_mode(sched_uid) == "group"

        _dissolve_group_via_service(ctx["email"], int(group_id))

        assert _scheduled_assign_mode(sched_uid) == ""


class TestScheduledAssignmentDummyDeletion:
    """Kicking a personal offline buddy resets assignment to none."""

    def test_kick_dummy_resets_assignment(self, driver, w, ctx):
        dummy_uid = _create_personal_dummy(ctx["email"], "Offline Kick Me")
        sched_uid = _create_scheduled_with_dummy_upfront(
            ctx["email"], int(dummy_uid), int(dummy_uid)
        )

        assert _scheduled_assign_mode(sched_uid) == "single"

        _kick_dummy_via_service(ctx["email"], int(dummy_uid))

        assert _scheduled_assign_mode(sched_uid) == ""


class TestScheduledAssignmentGroupMemberRemoved:
    """
    When a user is kicked from a group, only that user's scheduled expenses
    lose their assignment. Other members' scheduled expenses are unaffected.
    """

    def test_remove_group_member_resets_only_kicked_users_assignment(self, driver, w, ctx):
        ctx2 = setup_user(driver, w)
        _create_buddy_link(ctx["email"], ctx2["email"])
        group_id = _create_group(ctx["email"], "Remove Member Group")
        _add_group_member(int(group_id), ctx2["email"])

        admin_pk = _feuser_pk(ctx["email"])
        member_pk = _feuser_pk(ctx2["email"])

        # ctx2 (the one who will be kicked) owns this scheduled expense
        kicked_sched_uid = _create_scheduled_with_project(
            ctx2["email"], int(group_id), [admin_pk, member_pk],
            title="Sched By Kicked Member"
        )

        # ctx (admin, stays in group) also has a scheduled expense for the same group
        admin_sched_uid = _create_scheduled_with_project(
            ctx["email"], int(group_id), [admin_pk, member_pk],
            title="Sched By Admin"
        )

        assert _scheduled_assign_mode(kicked_sched_uid) == "group"
        assert _scheduled_assign_mode(admin_sched_uid) == "group"

        _remove_member_via_service(ctx["email"], ctx2["email"], int(group_id))

        # Kicked user's scheduled expense loses its assignment
        assert _scheduled_assign_mode(kicked_sched_uid) == ""
        # Admin's scheduled expense is unaffected — they're still in the group
        assert _scheduled_assign_mode(admin_sched_uid) == "group"

        cleanup_user(ctx2["email"])

    def test_third_member_keeps_assignment_with_equal_shares(self, driver, w, ctx):
        """
        3-member group (admin, kicked, stayer). After kicking one:
        - kicked user's scheduled expense is cleared
        - stayer's scheduled expense keeps the group assignment
        - stayer's spendings are updated to equal shares among the two remaining members
        """
        ctx2 = setup_user(driver, w)
        ctx3 = setup_user(driver, w)
        _create_buddy_link(ctx["email"], ctx2["email"])
        _create_buddy_link(ctx["email"], ctx3["email"])
        group_id = _create_group(ctx["email"], "Three Member Group")
        _add_group_member(int(group_id), ctx2["email"])
        _add_group_member(int(group_id), ctx3["email"])

        admin_pk = _feuser_pk(ctx["email"])
        kicked_pk = _feuser_pk(ctx2["email"])
        stayer_pk = _feuser_pk(ctx3["email"])

        # Each has a scheduled expense for the group, split equally among all 3
        kicked_sched_uid = _create_scheduled_with_project(
            ctx2["email"], int(group_id), [admin_pk, kicked_pk, stayer_pk],
            title="Kicked Sched 3M"
        )
        stayer_sched_uid = _create_scheduled_with_project(
            ctx3["email"], int(group_id), [admin_pk, kicked_pk, stayer_pk],
            title="Stayer Sched 3M"
        )

        assert _scheduled_assign_mode(kicked_sched_uid) == "group"
        assert _scheduled_assign_mode(stayer_sched_uid) == "group"

        _remove_member_via_service(ctx["email"], ctx2["email"], int(group_id))

        # Kicked user's assignment is gone
        assert _scheduled_assign_mode(kicked_sched_uid) == ""

        # Stayer keeps the group assignment
        assert _scheduled_assign_mode(stayer_sched_uid) == "group"

        # Stayer's spendings are now 50/50 between admin and stayer
        spendings = _scheduled_spendings(stayer_sched_uid)
        assert len(spendings) == 2, f"Expected 2 participants after kick, got: {spendings}"
        by_id = {s["id"]: s["share_percent"] for s in spendings}
        assert kicked_pk not in by_id, "Kicked member still in spendings"
        assert admin_pk in by_id, "Admin missing from spendings"
        assert stayer_pk in by_id, "Stayer missing from spendings"
        assert abs(by_id[admin_pk] - 50.0) < 0.01, f"Admin share should be 50, got {by_id[admin_pk]}"
        assert abs(by_id[stayer_pk] - 50.0) < 0.01, f"Stayer share should be 50, got {by_id[stayer_pk]}"

        cleanup_user(ctx2["email"])
        cleanup_user(ctx3["email"])


class TestScheduledAssignmentDirectBuddyRemoved:
    """Removing a direct buddy (kick_actual) resets single-mode assignment to none."""

    def test_kick_actual_resets_direct_buddy_assignment(self, driver, w, ctx):
        ctx2 = setup_user(driver, w)
        _create_buddy_link(ctx["email"], ctx2["email"])
        buddy_pk = _feuser_pk(ctx2["email"])

        sched_uid = _create_scheduled_with_feuser_participant(
            ctx["email"], buddy_pk, title="Direct Buddy Sched"
        )

        assert _scheduled_assign_mode(sched_uid) == "single"

        _kick_actual_via_service(ctx["email"], ctx2["email"])

        assert _scheduled_assign_mode(sched_uid) == ""

        cleanup_user(ctx2["email"])
