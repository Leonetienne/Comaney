"""
Verify that last_mod is updated on every significant mutation.
No browser or HTTP requests: all operations go through docker exec django shell.
Run with: pytest tests/e2e/test_lastmod.py -v
"""
import time
import subprocess
import uuid

import pytest

from helpers import DOCKER_WEB, run_cmd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shell(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, f"Shell failed:\n{r.stderr}\nCode: {code}"
    return r.stdout.strip()


def _mk_email() -> str:
    return f"lastmod_{uuid.uuid4().hex[:8]}@test.local"


def _create_user(email: str) -> None:
    run_cmd("create_user", email, "-p", "TestPass123!")


def _delete_user(email: str) -> None:
    run_cmd("delete_user", email, "--yes")


# ---------------------------------------------------------------------------
# FeUser
# ---------------------------------------------------------------------------

class TestFeUserLastMod:
    @pytest.fixture(scope="class")
    def email(self):
        e = _mk_email()
        _create_user(e)
        yield e
        _delete_user(e)

    def _lm(self, email: str) -> str:
        return _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{email}').last_mod.isoformat())"
        )

    def test_update_lastmod_method(self, email):
        before = self._lm(email)
        time.sleep(0.05)
        _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); u.update_lastmod()"
        )
        assert self._lm(email) > before

    def test_profile_field_save(self, email):
        before = self._lm(email)
        time.sleep(0.05)
        _shell(
            f"from feusers.models import FeUser; from django.utils import timezone; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"u.first_name = 'Changed'; u.last_mod = timezone.now(); "
            f"u.save(update_fields=['first_name', 'last_mod'])"
        )
        assert self._lm(email) > before

    def test_currency_save(self, email):
        before = self._lm(email)
        time.sleep(0.05)
        _shell(
            f"from feusers.models import FeUser; from django.utils import timezone; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"u.currency = '$'; u.last_mod = timezone.now(); "
            f"u.save(update_fields=['currency', 'last_mod'])"
        )
        assert self._lm(email) > before


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class TestCategoryLastMod:
    @pytest.fixture(scope="class")
    def cat_uid(self):
        email = _mk_email()
        _create_user(email)
        uid = _shell(
            f"from budget.models import Category; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"print(Category.objects.create(owning_feuser=u, title='LM Cat').uid)"
        )
        yield int(uid)
        _shell(f"from budget.models import Category; Category.objects.filter(uid={uid}).delete()")
        _delete_user(email)

    def _lm(self, uid: int) -> str:
        return _shell(
            f"from budget.models import Category; "
            f"print(Category.objects.get(uid={uid}).last_mod.isoformat())"
        )

    def test_created_with_last_mod(self, cat_uid):
        lm = self._lm(cat_uid)
        assert lm, "last_mod should be set on creation"

    def test_rename_bumps_last_mod(self, cat_uid):
        before = self._lm(cat_uid)
        time.sleep(0.05)
        _shell(
            f"from budget.models import Category; from django.utils import timezone; "
            f"c = Category.objects.get(uid={cat_uid}); "
            f"c.title = 'LM Cat Renamed'; c.last_mod = timezone.now(); "
            f"c.save(update_fields=['title', 'last_mod'])"
        )
        assert self._lm(cat_uid) > before


# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------

class TestTagLastMod:
    @pytest.fixture(scope="class")
    def tag_uid(self):
        email = _mk_email()
        _create_user(email)
        uid = _shell(
            f"from budget.models import Tag; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"print(Tag.objects.create(owning_feuser=u, title='LM Tag').uid)"
        )
        yield int(uid)
        _shell(f"from budget.models import Tag; Tag.objects.filter(uid={uid}).delete()")
        _delete_user(email)

    def _lm(self, uid: int) -> str:
        return _shell(
            f"from budget.models import Tag; "
            f"print(Tag.objects.get(uid={uid}).last_mod.isoformat())"
        )

    def test_rename_bumps_last_mod(self, tag_uid):
        before = self._lm(tag_uid)
        time.sleep(0.05)
        _shell(
            f"from budget.models import Tag; from django.utils import timezone; "
            f"t = Tag.objects.get(uid={tag_uid}); "
            f"t.title = 'LM Tag Renamed'; t.last_mod = timezone.now(); "
            f"t.save(update_fields=['title', 'last_mod'])"
        )
        assert self._lm(tag_uid) > before


# ---------------------------------------------------------------------------
# Expense
# ---------------------------------------------------------------------------

class TestExpenseLastMod:
    @pytest.fixture(scope="class")
    def exp_uid(self):
        email = _mk_email()
        _create_user(email)
        uid = _shell(
            f"from budget.models import Expense; from feusers.models import FeUser; "
            f"from decimal import Decimal; import datetime; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"e = Expense.objects.create(owning_feuser=u, title='LM Exp', "
            f"  type='expense', value=Decimal('10.00'), date_due=datetime.date.today(), settled=True); "
            f"print(e.uid)"
        )
        yield int(uid)
        _shell(f"from budget.models import Expense; Expense.objects.filter(uid={uid}).delete()")
        _delete_user(email)

    def _lm(self, uid: int) -> str:
        return _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(uid={uid}).last_mod.isoformat())"
        )

    def test_created_with_last_mod(self, exp_uid):
        assert self._lm(exp_uid), "last_mod should be set on creation"

    def test_full_save_bumps_last_mod(self, exp_uid):
        before = self._lm(exp_uid)
        time.sleep(0.05)
        _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(uid={exp_uid}); "
            f"e.title = 'LM Exp Edited'; e.save()"
        )
        assert self._lm(exp_uid) > before

    def test_partial_save_bumps_last_mod(self, exp_uid):
        before = self._lm(exp_uid)
        time.sleep(0.05)
        _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(uid={exp_uid}); "
            f"e.settled = False; e.save(update_fields=['settled'])"
        )
        assert self._lm(exp_uid) > before


# ---------------------------------------------------------------------------
# ScheduledExpense
# ---------------------------------------------------------------------------

class TestScheduledExpenseLastMod:
    @pytest.fixture(scope="class")
    def sched_uid(self):
        email = _mk_email()
        _create_user(email)
        uid = _shell(
            f"from budget.models import ScheduledExpense; from feusers.models import FeUser; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"s = ScheduledExpense.objects.create(owning_feuser=u, title='LM Sched', "
            f"  type='expense', value=Decimal('5.00')); print(s.uid)"
        )
        yield int(uid)
        _shell(f"from budget.models import ScheduledExpense; ScheduledExpense.objects.filter(uid={uid}).delete()")
        _delete_user(email)

    def _lm(self, uid: int) -> str:
        return _shell(
            f"from budget.models import ScheduledExpense; "
            f"print(ScheduledExpense.objects.get(uid={uid}).last_mod.isoformat())"
        )

    def test_full_save_bumps_last_mod(self, sched_uid):
        before = self._lm(sched_uid)
        time.sleep(0.05)
        _shell(
            f"from budget.models import ScheduledExpense; "
            f"s = ScheduledExpense.objects.get(uid={sched_uid}); "
            f"s.title = 'LM Sched Edited'; s.save()"
        )
        assert self._lm(sched_uid) > before

    def test_partial_save_bumps_last_mod(self, sched_uid):
        before = self._lm(sched_uid)
        time.sleep(0.05)
        _shell(
            f"from budget.models import ScheduledExpense; "
            f"s = ScheduledExpense.objects.get(uid={sched_uid}); "
            f"s.deactivated = True; s.save(update_fields=['deactivated'])"
        )
        assert self._lm(sched_uid) > before


# ---------------------------------------------------------------------------
# DashboardCard
# ---------------------------------------------------------------------------

class TestDashboardCardLastMod:
    @pytest.fixture(scope="class")
    def card_uid(self):
        email = _mk_email()
        _create_user(email)
        uid = _shell(
            f"from budget.models import Dashboard, DashboardCard; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = Dashboard.objects.create(owning_feuser=u, title='Test Dashboard'); "
            f"c = DashboardCard.objects.create(owning_feuser=u, dashboard=d, yaml_config='type: cell\\n'); "
            f"print(c.uid)"
        )
        yield int(uid)
        _shell(f"from budget.models import DashboardCard; DashboardCard.objects.filter(uid={uid}).delete()")
        _delete_user(email)

    def _lm(self, uid: int) -> str:
        return _shell(
            f"from budget.models import DashboardCard; "
            f"print(DashboardCard.objects.get(uid={uid}).last_mod.isoformat())"
        )

    def test_save_bumps_last_mod(self, card_uid):
        before = self._lm(card_uid)
        time.sleep(0.05)
        _shell(
            f"from budget.models import DashboardCard; "
            f"c = DashboardCard.objects.get(uid={card_uid}); "
            f"c.yaml_config = 'type: cell\\ntitle: updated\\n'; c.save(update_fields=['yaml_config'])"
        )
        assert self._lm(card_uid) > before


# ---------------------------------------------------------------------------
# DummyUser
# ---------------------------------------------------------------------------

class TestDummyUserLastMod:
    @pytest.fixture(scope="class")
    def dummy_uid(self):
        email = _mk_email()
        _create_user(email)
        uid = _shell(
            f"from buddies.models import DummyUser; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"print(DummyUser.objects.create(owning_feuser=u, display_name='LM Dummy').uid)"
        )
        yield int(uid)
        _shell(f"from buddies.models import DummyUser; DummyUser.objects.filter(uid={uid}).delete()")
        _delete_user(email)

    def _lm(self, uid: int) -> str:
        return _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.get(uid={uid}).last_mod.isoformat())"
        )

    def test_rename_bumps_last_mod(self, dummy_uid):
        before = self._lm(dummy_uid)
        time.sleep(0.05)
        _shell(
            f"from buddies.models import DummyUser; from django.utils import timezone; "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"d.display_name = 'LM Dummy Renamed'; d.last_mod = timezone.now(); "
            f"d.save(update_fields=['display_name', 'last_mod'])"
        )
        assert self._lm(dummy_uid) > before

    def test_update_lastmod_method(self, dummy_uid):
        before = self._lm(dummy_uid)
        time.sleep(0.05)
        _shell(
            f"from buddies.models import DummyUser; "
            f"DummyUser.objects.get(uid={dummy_uid}).update_lastmod()"
        )
        assert self._lm(dummy_uid) > before


# ---------------------------------------------------------------------------
# BuddySpending
# ---------------------------------------------------------------------------

class TestBuddySpendingLastMod:
    @pytest.fixture(scope="class")
    def bs_uid(self):
        email = _mk_email()
        _create_user(email)
        uid = _shell(
            f"from budget.models import Expense; from buddies.models import BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; import datetime; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"e = Expense.objects.create(owning_feuser=u, title='LM BS Exp', "
            f"  type='expense', value=Decimal('20.00'), date_due=datetime.date.today(), settled=True); "
            f"bs = BuddySpending.objects.create(expense=e, participant_feuser=u, share_percent=100); "
            f"print(bs.uid)"
        )
        yield int(uid)
        _shell(f"from buddies.models import BuddySpending; BuddySpending.objects.filter(uid={uid}).delete()")
        _delete_user(email)

    def _lm(self, uid: int) -> str:
        return _shell(
            f"from buddies.models import BuddySpending; "
            f"print(BuddySpending.objects.get(uid={uid}).last_mod.isoformat())"
        )

    def test_approval_state_change_bumps_last_mod(self, bs_uid):
        before = self._lm(bs_uid)
        time.sleep(0.05)
        _shell(
            f"from buddies.models import BuddySpending; from django.utils import timezone; "
            f"bs = BuddySpending.objects.get(uid={bs_uid}); "
            f"bs.approval_state = 1; bs.last_mod = timezone.now(); "
            f"bs.save(update_fields=['approval_state', 'last_mod'])"
        )
        assert self._lm(bs_uid) > before


# ---------------------------------------------------------------------------
# ExpenseDataOverlay
# ---------------------------------------------------------------------------

class TestExpenseDataOverlayLastMod:
    @pytest.fixture(scope="class")
    def overlay_uid(self):
        email = _mk_email()
        _create_user(email)
        uid = _shell(
            f"from budget.models import Expense, ExpenseDataOverlay; "
            f"from feusers.models import FeUser; from decimal import Decimal; import datetime; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"e = Expense.objects.create(owning_feuser=u, title='LM Ov Exp', "
            f"  type='expense', value=Decimal('5.00'), date_due=datetime.date.today(), settled=True); "
            f"ov = ExpenseDataOverlay.objects.create(expense=e, feuser=u, note='hello'); "
            f"print(ov.pk)"
        )
        yield int(uid)
        _shell(f"from budget.models import ExpenseDataOverlay; ExpenseDataOverlay.objects.filter(pk={uid}).delete()")
        _delete_user(email)

    def _lm(self, uid: int) -> str:
        return _shell(
            f"from budget.models import ExpenseDataOverlay; "
            f"print(ExpenseDataOverlay.objects.get(pk={uid}).last_mod.isoformat())"
        )

    def test_note_update_bumps_last_mod(self, overlay_uid):
        before = self._lm(overlay_uid)
        time.sleep(0.05)
        _shell(
            f"from budget.models import ExpenseDataOverlay; from django.utils import timezone; "
            f"ov = ExpenseDataOverlay.objects.get(pk={overlay_uid}); "
            f"ov.note = 'updated'; ov.last_mod = timezone.now(); "
            f"ov.save(update_fields=['note', 'last_mod'])"
        )
        assert self._lm(overlay_uid) > before


# ---------------------------------------------------------------------------
# ProjectMember sorting
# ---------------------------------------------------------------------------

class TestProjectMemberLastMod:
    @pytest.fixture(scope="class")
    def member_uid(self):
        email = _mk_email()
        _create_user(email)
        uid = _shell(
            f"from buddies.models import Project, ProjectMember; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"p = Project.objects.create(name='LM PM Project', admin_feuser=u); "
            f"m = ProjectMember.objects.create(group=p, feuser=u, sorting=1); "
            f"print(m.uid)"
        )
        yield int(uid)
        _shell(f"from buddies.models import ProjectMember; m = ProjectMember.objects.filter(uid={uid}).first(); m and m.group.delete()")
        _delete_user(email)

    def _lm(self, uid: int) -> str:
        return _shell(
            f"from buddies.models import ProjectMember; "
            f"print(ProjectMember.objects.get(uid={uid}).last_mod.isoformat())"
        )

    def test_sorting_update_bumps_last_mod(self, member_uid):
        before = self._lm(member_uid)
        time.sleep(0.05)
        _shell(
            f"from buddies.models import ProjectMember; from django.utils import timezone; "
            f"ProjectMember.objects.filter(uid={member_uid}).update(sorting=2, last_mod=timezone.now())"
        )
        assert self._lm(member_uid) > before
