"""
Personal offline-buddy self-merge: a user merges their own offline buddy
directly into themselves. Immediate, like dummy-into-dummy merge - there's
no second party to ask. Folds participation shares back into the owner's
implicit share (no longer a buddy expense) and transfers upfront-payer
expenses to the owner directly.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _confirm, _create_buddy_link, _get_pk


# ---------------------------------------------------------------------------
# Merging a participant dummy into yourself drops the split row entirely
# ---------------------------------------------------------------------------

class TestPersonalSelfMergeParticipant:
    """A owns an expense split with her offline dummy; merging the dummy into
    herself drops the split row - the expense becomes fully hers, no longer
    a buddy expense."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Inga", last_name="Selfmerge")
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Self Merge Dummy'); "
            f"print(d.uid)"
        ).strip()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Was Shared With Self', "
            f"  type='expense', value=Decimal('100.00'), settled=False, buddy_approved=True); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, share_percent=Decimal('30')); "
            f"print(e.pk)"
        ).strip()
        ctx = {"a": a, "dummy_uid": dummy_uid, "expense_pk": expense_pk}
        yield ctx
        cleanup_user(a["email"])

    def test_yourself_option_present(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        select_el = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']} select[name='target_key']")
        values = [o.get_attribute("value") for o in select_el.find_elements(By.TAG_NAME, "option")]
        assert "self" in values, "Yourself must be a selectable merge target"

    def test_a_merges_dummy_into_self(self, driver, w, ctx):
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value("self")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "/buddies/my-buddies/" in driver.current_url

    def test_dummy_gone_no_longer_a_buddy_expense(self, driver, w, ctx):
        gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).count())"
        )
        assert gone == "0", "Dummy must be deleted after self-merge"

        assert _shell(
            f"from budget.models import Expense; print(Expense.objects.filter(pk={ctx['expense_pk']}).exists())"
        ) == "True", "The expense itself must not be lost"

        row_count = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['expense_pk']}); "
            f"print(e.buddy_spendings.count())"
        )
        assert row_count == "0", \
            "The dropped participation row must leave no buddy_spendings rows - it's no longer a buddy expense"

        note = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['expense_pk']}).note)"
        )
        assert "Original participant was: Self Merge Dummy" in note


# ---------------------------------------------------------------------------
# Merging an upfront-payer dummy into yourself: you become the real owner
# ---------------------------------------------------------------------------

class TestPersonalSelfMergeUpfrontPayer:
    """A's offline dummy fronted the cash for an expense (is_dummy=True,
    upfront_payee_dummy=dummy). Self-merging it makes A the real owner."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Joost", last_name="Selfpayer")
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Self Payer Dummy'); "
            f"print(d.uid)"
        ).strip()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Self Fronted The Cash', "
            f"  type='expense', value=Decimal('50.00'), settled=False, buddy_approved=True, "
            f"  is_dummy=True, upfront_payee_dummy=d); "
            f"print(e.pk)"
        ).strip()
        ctx = {"a": a, "dummy_uid": dummy_uid, "expense_pk": expense_pk}
        yield ctx
        cleanup_user(a["email"])

    def test_a_merges_dummy_into_self(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value("self")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)

    def test_ownership_becomes_real(self, driver, w, ctx):
        state = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['expense_pk']}); "
            f"print(e.owning_feuser_id, e.is_dummy, e.upfront_payee_dummy_id)"
        )
        owning_feuser_id, is_dummy, upfront_payee_dummy_id = state.split()
        assert owning_feuser_id == _get_pk(ctx["a"]["email"])
        assert is_dummy == "False"
        assert upfront_payee_dummy_id == "None"
        gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).count())"
        )
        assert gone == "0"


# ---------------------------------------------------------------------------
# Self-merge clears stale references in recurring schedules
# ---------------------------------------------------------------------------

class TestPersonalSelfMergeScheduledCleanup:
    """A dummy referenced in a recurring expense's split must not survive
    self-merge as a stale reference."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Kira", last_name="Selfsched")
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Self Sched Dummy'); "
            f"print(d.uid)"
        ).strip()
        sched_pk = _shell(
            f"from budget.models import ScheduledExpense; "
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; import json; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"se = ScheduledExpense.objects.create(owning_feuser=u, title='Recurring Self Merge', "
            f"  type='expense', value=Decimal('40.00'), assign_buddy_mode='single', assign_upfront_type='me', "
            f"  assign_spendings_json=json.dumps(["
            f"    {{'type': 'dummy', 'id': d.uid, 'share_percent': 50.0}},"
            f"  ])); "
            f"print(se.pk)"
        ).strip()
        ctx = {"a": a, "dummy_uid": dummy_uid, "sched_pk": sched_pk}
        yield ctx
        cleanup_user(a["email"])

    def test_a_merges_dummy_into_self(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value("self")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)

    def test_schedule_no_longer_references_dummy(self, driver, w, ctx):
        sched_json = _shell(
            f"from budget.models import ScheduledExpense; "
            f"se = ScheduledExpense.objects.get(pk={ctx['sched_pk']}); "
            f"print(se.assign_spendings_json)"
        )
        assert f'"id": {ctx["dummy_uid"]}' not in sched_json, \
            f"Recurring schedule must not keep a stale reference to the deleted dummy: {sched_json}"


# ---------------------------------------------------------------------------
# Self-merge is blocked while an outgoing merge request is pending for that
# dummy, same as the immediate dummy-into-dummy path
# ---------------------------------------------------------------------------

class TestPersonalSelfMergeBlockedWhilePending:
    """A sent a merge request for her dummy to an already-linked buddy B;
    self-merging the same dummy before B responds must be rejected."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Lior", last_name="Selfpending")
        b = setup_user(None, None, first_name="Mira", last_name="Linked")
        _create_buddy_link(a["email"], b["email"])
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Self Pending Dummy'); "
            f"print(d.uid)"
        ).strip()
        _shell(
            f"from buddies.services import BuddyLifecycleService; "
            f"from feusers.models import FeUser; from buddies.models import DummyUser; "
            f"a = FeUser.objects.get(email='{a['email']}'); b = FeUser.objects.get(email='{b['email']}'); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"BuddyLifecycleService.request_merge_with_feuser(a, d, b)"
        )
        ctx = {"a": a, "b": b, "dummy_uid": dummy_uid}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_self_merge_blocked_while_request_pending(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value("self")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "pending merge request" in driver.page_source.lower()
        exists = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).exists())"
        )
        assert exists == "True", "Dummy must survive: self-merge must be rejected while a request is pending"
