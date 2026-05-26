"""
Personal offline-buddy-into-offline-buddy merge: immediate, no approval needed.
Replaces the old free-text-email "Invite as user" flow for this case.
"""
import subprocess
import time
import uuid

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user, fill, click, DOCKER_WEB, PASSWORD
from bhelpers import _shell, _confirm, _create_buddy_link, _create_group


# ---------------------------------------------------------------------------
# A merges one offline buddy into another
# ---------------------------------------------------------------------------

class TestPersonalDummyIntoDummyMerge:
    """A has two offline buddies; merges the source into the target from the '...' menu."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Mona", last_name="Merger")
        ids = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d1 = DummyUser.objects.create(owning_feuser=u, display_name='Source Dummy'); "
            f"d2 = DummyUser.objects.create(owning_feuser=u, display_name='Target Dummy'); "
            f"print(d1.uid, d2.uid)"
        )
        d1_uid, d2_uid = ids.split()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d1 = DummyUser.objects.get(uid={d1_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Source Dummy Expense', "
            f"  type='expense', value=Decimal('40.00'), settled=False, buddy_approved=True); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d1, share_percent=Decimal('50')); "
            f"print(e.pk)"
        )
        ctx = {"a": a, "d1_uid": d1_uid, "d2_uid": d2_uid, "expense_pk": expense_pk.strip()}
        yield ctx
        cleanup_user(a["email"])

    def test_merge_into_option_visible_not_invite_as_user(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert len(driver.find_elements(By.XPATH, "//*[contains(text(),'Invite as user')]")) == 0, \
            "The old 'Invite as user' option must be gone"
        assert driver.find_elements(By.ID, f"merge-btn-{ctx['d1_uid']}"), \
            "'Merge into...' option must be visible for an offline buddy"

    def test_merge_form_has_select_not_email_input(self, driver, w, ctx):
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['d1_uid']}")
        assert len(form.find_elements(By.CSS_SELECTOR, "input[name='email']")) == 0
        assert len(form.find_elements(By.CSS_SELECTOR, "select[name='target_key']")) == 1

    def test_a_merges_dummy_into_dummy(self, driver, w, ctx):
        driver.find_element(By.ID, f"merge-btn-{ctx['d1_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['d1_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"d{ctx['d2_uid']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "/buddies/my-buddies/" in driver.current_url

    def test_source_dummy_gone_target_remains(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert "Source Dummy" not in driver.page_source
        assert "Target Dummy" in driver.page_source

    def test_expense_history_transferred_and_source_deleted(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import DummyUser, BuddySpending; "
            f"d2 = DummyUser.objects.get(uid={ctx['d2_uid']}); "
            f"print(BuddySpending.objects.filter(participant_dummy=d2).count())"
        )
        assert count == "1", "Source dummy's BuddySpending must now belong to the target dummy"
        gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['d1_uid']}).count())"
        )
        assert gone == "0", "The source dummy must be deleted after merging"

    def test_note_records_original_participant(self, driver, w, ctx):
        note = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['expense_pk']}).note)"
        )
        assert "Original participant was: Source Dummy" in note, \
            f"Expense note must record the merged-away participant's name, got: {note!r}"


# ---------------------------------------------------------------------------
# Merging a dummy that fronted cash for an expense: the audit note on that
# expense must be merge-neutral, not the old archive-only "Archived from:" text.
# ---------------------------------------------------------------------------

class TestDummyIntoDummyMergeAnnotatesUpfrontPayerNote:
    """A has two offline buddies; the source dummy fronted cash for an expense.
    After merging source into target, the expense's note must record who
    originally paid, without implying anything was archived."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Nora", last_name="Payer")
        ids = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d1 = DummyUser.objects.create(owning_feuser=u, display_name='Fronting Dummy'); "
            f"d2 = DummyUser.objects.create(owning_feuser=u, display_name='Receiving Dummy'); "
            f"print(d1.uid, d2.uid)"
        )
        d1_uid, d2_uid = ids.split()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d1 = DummyUser.objects.get(uid={d1_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Fronted Cash Expense', "
            f"  type='expense', value=Decimal('60.00'), settled=False, buddy_approved=True, "
            f"  is_dummy=True, upfront_payee_dummy=d1); "
            f"print(e.pk)"
        )
        ctx = {"a": a, "d1_uid": d1_uid, "d2_uid": d2_uid, "expense_pk": expense_pk.strip()}
        yield ctx
        cleanup_user(a["email"])

    def test_a_merges_fronting_dummy_into_receiving_dummy(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['d1_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['d1_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"d{ctx['d2_uid']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "/buddies/my-buddies/" in driver.current_url

    def test_note_is_merge_neutral_not_archive_wording(self, driver, w, ctx):
        note = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['expense_pk']}).note)"
        )
        assert "Originally paid by: Fronting Dummy" in note, \
            f"Expense note must record who originally paid, got: {note!r}"
        assert "Archived from:" not in note, \
            f"A regular dummy-into-dummy merge must never use archive-only wording, got: {note!r}"

    def test_payer_reassigned_to_target(self, driver, w, ctx):
        payee_uid = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['expense_pk']}).upfront_payee_dummy_id)"
        )
        assert payee_uid == ctx["d2_uid"], "The target dummy must become the new upfront payer"


# ---------------------------------------------------------------------------
# Merging two dummies who already share a four-way split expense: shares must
# sum into one row, other participants must stay untouched.
# ---------------------------------------------------------------------------

class TestDummyIntoDummyMergeSumsConflictingShares:
    """anna 10%, frank 20%, mario 35%, tom 35% on one expense (all A's offline
    buddies). Merging mario into tom must leave anna 10%, frank 20%, tom 70%
    in a single row, not a duplicate row, and the expense must not be lost."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Quincy", last_name="Owner")
        ids = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"anna = DummyUser.objects.create(owning_feuser=u, display_name='Anna Split'); "
            f"frank = DummyUser.objects.create(owning_feuser=u, display_name='Frank Split'); "
            f"mario = DummyUser.objects.create(owning_feuser=u, display_name='Mario Split'); "
            f"tom = DummyUser.objects.create(owning_feuser=u, display_name='Tom Split'); "
            f"print(anna.uid, frank.uid, mario.uid, tom.uid)"
        )
        anna_uid, frank_uid, mario_uid, tom_uid = ids.split()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"anna = DummyUser.objects.get(uid={anna_uid}); "
            f"frank = DummyUser.objects.get(uid={frank_uid}); "
            f"mario = DummyUser.objects.get(uid={mario_uid}); "
            f"tom = DummyUser.objects.get(uid={tom_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Four Way Split Personal', "
            f"  type='expense', value=Decimal('200.00'), settled=False, buddy_approved=True); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=anna, share_percent=Decimal('10')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=frank, share_percent=Decimal('20')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=mario, share_percent=Decimal('35')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=tom, share_percent=Decimal('35')); "
            f"print(e.pk)"
        )
        sched_pk = _shell(
            f"from budget.models import ScheduledExpense; "
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; import json; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"mario = DummyUser.objects.get(uid={mario_uid}); "
            f"tom = DummyUser.objects.get(uid={tom_uid}); "
            f"se = ScheduledExpense.objects.create(owning_feuser=u, title='Recurring Four Way', "
            f"  type='expense', value=Decimal('90.00'), assign_buddy_mode='single', assign_upfront_type='me', "
            f"  assign_spendings_json=json.dumps(["
            f"    {{'type': 'dummy', 'id': mario.uid, 'share_percent': 35.0}},"
            f"    {{'type': 'dummy', 'id': tom.uid, 'share_percent': 35.0}},"
            f"  ])); "
            f"print(se.pk)"
        )
        ctx = {
            "a": a, "expense_pk": expense_pk.strip(), "sched_pk": sched_pk.strip(),
            "mario_uid": mario_uid, "tom_uid": tom_uid,
        }
        yield ctx
        cleanup_user(a["email"])

    def test_merge_mario_into_tom(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['mario_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['mario_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"d{ctx['tom_uid']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "/buddies/my-buddies/" in driver.current_url

    def test_expense_not_lost_shares_summed_others_untouched(self, driver, w, ctx):
        rows = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['expense_pk']}); "
            f"print(chr(10).join(f'{{bs.participant_feuser or bs.participant_dummy}}|{{bs.share_percent}}' for bs in e.buddy_spendings.all()))"
        )
        assert _shell(
            f"from budget.models import Expense; print(Expense.objects.filter(pk={ctx['expense_pk']}).exists())"
        ) == "True", "The expense itself must not be lost"

        lines = [l for l in rows.splitlines() if l.strip()]
        shares = {l.split('|')[0]: l.split('|')[1] for l in lines}
        assert len(lines) == 3, f"Expected exactly 3 rows (anna, frank, tom), got: {shares}"
        assert shares.get("Anna Split") == "10.000", shares
        assert shares.get("Frank Split") == "20.000", shares
        assert shares.get("Tom Split") == "70.000", shares

        mario_gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['mario_uid']}).count())"
        )
        assert mario_gone == "0", "Mario must be deleted, with no stale references left behind"
        stale = _shell(
            f"from buddies.models import BuddySpending; "
            f"print(BuddySpending.objects.filter(participant_dummy_id={ctx['mario_uid']}).count())"
        )
        assert stale == "0", "No BuddySpending row may still reference the deleted dummy"

    def test_recurring_schedule_sums_shares_no_stale_reference(self, driver, w, ctx):
        sched_json = _shell(
            f"from budget.models import ScheduledExpense; "
            f"se = ScheduledExpense.objects.get(pk={ctx['sched_pk']}); "
            f"print(se.assign_spendings_json)"
        )
        assert f'"id": {ctx["mario_uid"]}' not in sched_json, \
            f"Recurring schedule must not keep a stale reference to the deleted dummy: {sched_json}"
        assert '"share_percent": 70.0' in sched_json, \
            f"Recurring schedule must sum mario's and tom's shares into one 70% entry: {sched_json}"


# ---------------------------------------------------------------------------
# Immediate dummy-into-dummy merge is blocked while a merge request is
# pending for the source dummy, same as the self-merge path: an outgoing
# request must never be silently orphaned out from under its recipient.
# ---------------------------------------------------------------------------

class TestPersonalDummyIntoDummyMergeBlockedWhilePending:
    """A sent a merge request for her dummy to an already-linked buddy B;
    immediately merging that same dummy into another offline buddy before B
    responds must be rejected."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Nadia", last_name="Pendingmerger")
        b = setup_user(None, None, first_name="Omar", last_name="Linked")
        _create_buddy_link(a["email"], b["email"])
        ids = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"source = DummyUser.objects.create(owning_feuser=u, display_name='Pending Source Dummy'); "
            f"other = DummyUser.objects.create(owning_feuser=u, display_name='Other Dummy'); "
            f"print(source.uid, other.uid)"
        )
        source_uid, other_uid = ids.split()
        _shell(
            f"from buddies.services import BuddyLifecycleService; "
            f"from feusers.models import FeUser; from buddies.models import DummyUser; "
            f"a = FeUser.objects.get(email='{a['email']}'); b = FeUser.objects.get(email='{b['email']}'); "
            f"d = DummyUser.objects.get(uid={source_uid}); "
            f"BuddyLifecycleService.request_merge_with_feuser(a, d, b)"
        )
        ctx = {"a": a, "b": b, "source_uid": source_uid, "other_uid": other_uid}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_dummy_into_dummy_merge_blocked_while_request_pending(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['source_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['source_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"d{ctx['other_uid']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "pending merge request" in driver.page_source.lower()
        exists = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['source_uid']}).exists())"
        )
        assert exists == "True", \
            "Source dummy must survive: dummy-into-dummy merge must be rejected while a request is pending"


# ---------------------------------------------------------------------------
# Merging an upfront-payer dummy into another dummy that already has an
# explicit participation row on that same expense: the stale row must be
# dropped, mirroring TestMergeRequestUpfrontPayerBecomesRealOwner (in
# test_merge_request_to_feuser.py) but for the immediate dummy-into-dummy
# path.
# ---------------------------------------------------------------------------

class TestDummyIntoDummyMergeUpfrontPayerConflict:
    """source (dummy) fronted the cash for an expense. anna (dummy, 30%) and
    target (dummy, 30%) are explicit participants; source's implicit share is
    40%. Merging source into target must point upfront_payee_dummy at target,
    remove target's now-stale 30% row, and leave only anna's 30% row (target's
    new implicit share is 70%, not 40%)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Petra", last_name="Conflictpayer")
        ids = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"source = DummyUser.objects.create(owning_feuser=u, display_name='Conflict Payer Dummy'); "
            f"target = DummyUser.objects.create(owning_feuser=u, display_name='Conflict Target Dummy'); "
            f"anna = DummyUser.objects.create(owning_feuser=u, display_name='Anna Conflict'); "
            f"print(source.uid, target.uid, anna.uid)"
        )
        source_uid, target_uid, anna_uid = ids.split()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"source = DummyUser.objects.get(uid={source_uid}); "
            f"target = DummyUser.objects.get(uid={target_uid}); "
            f"anna = DummyUser.objects.get(uid={anna_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Conflict Payer Expense', "
            f"  type='expense', value=Decimal('100.00'), settled=False, buddy_approved=True, "
            f"  is_dummy=True, upfront_payee_dummy=source); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=target, share_percent=Decimal('30')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=anna, share_percent=Decimal('30')); "
            f"print(e.pk)"
        )
        ctx = {
            "a": a, "expense_pk": expense_pk.strip(),
            "source_uid": source_uid, "target_uid": target_uid, "anna_uid": anna_uid,
        }
        yield ctx
        cleanup_user(a["email"])

    def test_a_merges_source_into_target(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['source_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['source_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"d{ctx['target_uid']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "/buddies/my-buddies/" in driver.current_url

    def test_payer_reassigned_stale_row_removed_anna_untouched(self, driver, w, ctx):
        state = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['expense_pk']}); "
            f"print(e.upfront_payee_dummy_id, e.is_dummy)"
        )
        upfront_payee_dummy_id, is_dummy = state.split()
        assert upfront_payee_dummy_id == ctx["target_uid"], "Target must become the new upfront payer"
        assert is_dummy == "True"

        rows = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['expense_pk']}); "
            f"print(chr(10).join(f'{{bs.participant_dummy_id}}|{{bs.share_percent}}' for bs in e.buddy_spendings.all()))"
        )
        lines = [l for l in rows.splitlines() if l.strip()]
        shares = {l.split('|')[0]: l.split('|')[1] for l in lines}
        assert len(lines) == 1, \
            f"target's stale self-participation row must be removed once it becomes the payer, got: {shares}"
        assert shares.get(ctx["anna_uid"]) == "30.000", shares
        implied_payer_share = 100 - sum(float(v) for v in shares.values())
        assert implied_payer_share == 70.0, \
            f"target's implicit payer share must be 70 (its old 30 + source's implicit 40), got {implied_payer_share}"

        note = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['expense_pk']}).note)"
        )
        assert "Originally paid by: Conflict Payer Dummy" in note, note

        source_gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['source_uid']}).count())"
        )
        assert source_gone == "0", "Source must be deleted, with no stale references left behind"


# ---------------------------------------------------------------------------
# Cross-scope merge is rejected: a personal dummy can never be merged into a
# project-scoped dummy. The "Merge into..." dropdown never offers one (it's
# built from the personal-scope dummy/buddy lists only), so this only
# matters as a backend guard against a forged request.
# ---------------------------------------------------------------------------

class TestPersonalDummyMergeRejectsProjectScopedTarget:
    """A's personal merge_dummy endpoint must reject a target_key pointing at
    a project-scoped dummy, even though the UI never offers one."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Quinta", last_name="Crossscope")
        source_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Personal Cross Source'); "
            f"print(d.uid)"
        ).strip()
        group_id = _create_group(a["email"], "Cross Scope Target Project")
        project_dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Project Cross Target'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        ).strip()
        ctx = {
            "a": a, "group_id": int(group_id),
            "source_uid": source_uid, "project_dummy_uid": project_dummy_uid,
        }
        yield ctx
        cleanup_user(a["email"])

    def test_merge_post_rejected_target_is_project_scoped(self, driver, w, ctx):
        status = _shell(
            f"from django.test import Client; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"c = Client(); s = c.session; s['feuser_id'] = u.pk; s.save(); "
            f"resp = c.post('/buddies/dummy/{ctx['source_uid']}/merge/', {{'target_key': 'd{ctx['project_dummy_uid']}'}}); "
            f"print(resp.status_code)"
        ).strip()
        assert status == "404", \
            f"Merging a personal dummy into a project-scoped target must be rejected, got status {status}"

        source_exists = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['source_uid']}).exists())"
        )
        assert source_exists == "True", "Source dummy must survive a rejected cross-scope merge"

        project_dummy_untouched = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['project_dummy_uid']}).exists())"
        )
        assert project_dummy_untouched == "True", "Project-scoped target must be untouched"


# ---------------------------------------------------------------------------
# Demo users never see "Merge into..." for their own offline buddies
# ---------------------------------------------------------------------------

def _demo_users_enabled() -> bool:
    return _shell("from django.conf import settings; print(settings.ENABLE_DEMO_USERS)") == "True"


def _create_demo_member(first_name: str, last_name: str) -> dict:
    email = f"sel.{uuid.uuid4().hex[:8]}@example.com"
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py",
         "create_user", email, "-p", PASSWORD, "--demo",
         "--first-name", first_name, "--last-name", last_name],
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0, f"create_user --demo failed:\n{r.stderr}"
    return {"email": email, "password": PASSWORD}


def _demo_login_and_accept(driver, w, demo_ctx):
    driver.delete_all_cookies()
    driver.get(_url("/login/"))
    fill(w, By.ID, "id_email", demo_ctx["email"])
    fill(w, By.ID, "id_password", demo_ctx["password"])
    click(w, By.CSS_SELECTOR, "button[type=submit]")
    time.sleep(2)
    if "/demo-banner/" in driver.current_url:
        click(w, By.ID, "btn-demo-accept")
        time.sleep(2)


class TestDemoUserCannotMergePersonalDummy:
    """A demo user's offline buddies never show the Merge into... option."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        if not _demo_users_enabled():
            pytest.skip("ENABLE_DEMO_USERS is not set on this server")
        demo = _create_demo_member("Xena", "Demo")
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{demo['email']}'); "
            f"d1 = DummyUser.objects.create(owning_feuser=u, display_name='Demo Dummy One'); "
            f"DummyUser.objects.create(owning_feuser=u, display_name='Demo Dummy Two'); "
            f"print(d1.uid)"
        )
        yield {"demo": demo, "dummy_uid": dummy_uid.strip()}
        cleanup_user(demo["email"])

    def test_no_merge_option_for_demo_user(self, driver, w, ctx):
        _demo_login_and_accept(driver, w, ctx["demo"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert not driver.find_elements(By.ID, f"merge-btn-{ctx['dummy_uid']}"), \
            "Demo users must never see 'Merge into...' for their offline buddies"
