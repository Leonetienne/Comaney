"""
Project offline-member-into-offline-member merge: immediate, admin only.
Replaces the old free-text-email "Invite as user" flow for this case.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _confirm, _create_group, _add_group_member


def _settings_url(group_id) -> str:
    return _url(f"/projects/{group_id}/settings/")


# ---------------------------------------------------------------------------
# Admin merges one offline member into another
# ---------------------------------------------------------------------------

class TestProjectDummyIntoDummyMergeAdmin:
    """Admin has two offline members; merges the source into the target."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Nora", last_name="Owner")
        group_id = _create_group(admin["email"], "Dummy Merge Project")
        ids = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d1 = DummyUser.objects.create(owning_group=g, display_name='Source Member'); "
            f"ProjectMember.objects.create(group=g, dummy=d1); "
            f"d2 = DummyUser.objects.create(owning_group=g, display_name='Target Member'); "
            f"ProjectMember.objects.create(group=g, dummy=d2); "
            f"print(d1.uid, d2.uid)"
        )
        d1_uid, d2_uid = ids.split()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{admin['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d1 = DummyUser.objects.get(uid={d1_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Source Member Expense', "
            f"  type='expense', value=Decimal('30.00'), settled=False, buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d1, share_percent=Decimal('50')); "
            f"print(e.pk)"
        )
        ctx = {
            "admin": admin, "group_id": int(group_id), "d1_uid": d1_uid, "d2_uid": d2_uid,
            "expense_pk": expense_pk.strip(),
        }
        yield ctx
        cleanup_user(admin["email"])

    def test_merge_into_option_visible_not_invite_as_user(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        assert len(driver.find_elements(By.XPATH, "//*[contains(text(),'Invite as user')]")) == 0, \
            "The old 'Invite as user' option must be gone"
        assert driver.find_elements(By.ID, f"merge-btn-{ctx['d1_uid']}"), \
            "'Merge into...' option must be visible to the admin for an offline member"

    def test_merge_form_has_select_not_email_input(self, driver, w, ctx):
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['d1_uid']}")
        assert len(form.find_elements(By.CSS_SELECTOR, "input[name='email']")) == 0
        assert len(form.find_elements(By.CSS_SELECTOR, "select[name='target_key']")) == 1

    def test_admin_merges_dummy_into_dummy(self, driver, w, ctx):
        driver.find_element(By.ID, f"merge-btn-{ctx['d1_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['d1_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"d{ctx['d2_uid']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "/settings/" in driver.current_url

    def test_source_member_gone_target_remains(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        assert "Source Member" not in driver.page_source
        assert "Target Member" in driver.page_source

    def test_expense_history_transferred_and_source_deleted(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import DummyUser, BuddySpending; "
            f"d2 = DummyUser.objects.get(uid={ctx['d2_uid']}); "
            f"print(BuddySpending.objects.filter(participant_dummy=d2).count())"
        )
        assert count == "1", "Source member's BuddySpending must now belong to the target member"
        gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['d1_uid']}).count())"
        )
        assert gone == "0", "The source offline member must be deleted after merging"

    def test_note_records_original_participant(self, driver, w, ctx):
        note = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['expense_pk']}).note)"
        )
        assert "Original participant was: Source Member" in note, \
            f"Expense note must record the merged-away participant's name, got: {note!r}"


# ---------------------------------------------------------------------------
# Merging two offline members who already share a four-way split expense:
# shares must sum into one row, other participants must stay untouched.
# ---------------------------------------------------------------------------

class TestProjectDummyIntoDummyMergeSumsConflictingShares:
    """anna 10%, frank 20%, mario 35%, tom 35% on one project expense (all
    offline members). Merging mario into tom must leave anna 10%, frank 20%,
    tom 70% in a single row, not a duplicate row, and the expense must not be lost."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Rosa", last_name="Owner")
        group_id = _create_group(admin["email"], "Project Four Way Split")
        ids = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"anna = DummyUser.objects.create(owning_group=g, display_name='PAnna Split'); "
            f"ProjectMember.objects.create(group=g, dummy=anna); "
            f"frank = DummyUser.objects.create(owning_group=g, display_name='PFrank Split'); "
            f"ProjectMember.objects.create(group=g, dummy=frank); "
            f"mario = DummyUser.objects.create(owning_group=g, display_name='PMario Split'); "
            f"ProjectMember.objects.create(group=g, dummy=mario); "
            f"tom = DummyUser.objects.create(owning_group=g, display_name='PTom Split'); "
            f"ProjectMember.objects.create(group=g, dummy=tom); "
            f"print(anna.uid, frank.uid, mario.uid, tom.uid)"
        )
        anna_uid, frank_uid, mario_uid, tom_uid = ids.split()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{admin['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"anna = DummyUser.objects.get(uid={anna_uid}); "
            f"frank = DummyUser.objects.get(uid={frank_uid}); "
            f"mario = DummyUser.objects.get(uid={mario_uid}); "
            f"tom = DummyUser.objects.get(uid={tom_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Four Way Split Project', "
            f"  type='expense', value=Decimal('200.00'), settled=False, buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=anna, share_percent=Decimal('10')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=frank, share_percent=Decimal('20')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=mario, share_percent=Decimal('35')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=tom, share_percent=Decimal('35')); "
            f"print(e.pk)"
        )
        ctx = {
            "admin": admin, "group_id": int(group_id), "expense_pk": expense_pk.strip(),
            "mario_uid": mario_uid, "tom_uid": tom_uid,
        }
        yield ctx
        cleanup_user(admin["email"])

    def test_merge_mario_into_tom(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['mario_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['mario_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"d{ctx['tom_uid']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "/settings/" in driver.current_url

    def test_expense_not_lost_shares_summed_others_untouched(self, driver, w, ctx):
        assert _shell(
            f"from budget.models import Expense; print(Expense.objects.filter(pk={ctx['expense_pk']}).exists())"
        ) == "True", "The expense itself must not be lost"

        rows = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['expense_pk']}); "
            f"print(chr(10).join(f'{{bs.participant_feuser or bs.participant_dummy}}|{{bs.share_percent}}' for bs in e.buddy_spendings.all()))"
        )
        lines = [l for l in rows.splitlines() if l.strip()]
        shares = {l.split('|')[0]: l.split('|')[1] for l in lines}
        assert len(lines) == 3, f"Expected exactly 3 rows (anna, frank, tom), got: {shares}"
        assert shares.get("PAnna Split") == "10.000", shares
        assert shares.get("PFrank Split") == "20.000", shares
        assert shares.get("PTom Split") == "70.000", shares

        mario_gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['mario_uid']}).count())"
        )
        assert mario_gone == "0", "Mario must be deleted, with no stale references left behind"


# ---------------------------------------------------------------------------
# Non-admin members never see offline-member rows, so never see the option
# ---------------------------------------------------------------------------

class TestNonAdminNeverSeesProjectDummyMergeOption:
    """A regular (non-admin) member can see offline-member names, but never their
    '...' menu, so the merge option never appears for them."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Omar", last_name="Owner")
        member = setup_user(driver, w, first_name="Priya", last_name="Member")
        group_id = _create_group(admin["email"], "Non Admin Merge Project")
        _add_group_member(int(group_id), member["email"])
        _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Hidden Offline Member'); "
            f"ProjectMember.objects.create(group=g, dummy=d)"
        )
        ctx = {"admin": admin, "member": member, "group_id": int(group_id)}
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_non_admin_does_not_see_merge_option(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        assert "Hidden Offline Member" in driver.page_source, \
            "Non-admins can see the offline member's name"
        assert len(driver.find_elements(By.XPATH, "//*[contains(text(),'Merge into')]")) == 0
        dummy_card = driver.find_element(By.XPATH, "//*[contains(text(),'Hidden Offline Member')]/ancestor::*[contains(@class,'buddy-card-dummy')]")
        assert not dummy_card.find_elements(By.CSS_SELECTOR, ".ctx-menu-wrap"), \
            "Non-admins must not see any '...' menu on offline member rows"


# ---------------------------------------------------------------------------
# Immediate dummy-into-dummy merge is blocked while a merge request is
# pending for the source member, same as the self-merge path: an outgoing
# request must never be silently orphaned out from under its recipient.
# ---------------------------------------------------------------------------

class TestProjectDummyIntoDummyMergeBlockedWhilePending:
    """Admin sent a merge request for a project offline member to another
    real project member; immediately merging that same offline member into
    a different offline member before they respond must be rejected."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Rolf", last_name="Pendingadmin")
        carol = setup_user(None, None, first_name="Carla", last_name="Pendingmember")
        group_id = _create_group(admin["email"], "Dummy Pending Merge Project")
        _add_group_member(int(group_id), carol["email"])
        ids = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"source = DummyUser.objects.create(owning_group=g, display_name='Pending Source Member'); "
            f"ProjectMember.objects.create(group=g, dummy=source); "
            f"other = DummyUser.objects.create(owning_group=g, display_name='Other Member'); "
            f"ProjectMember.objects.create(group=g, dummy=other); "
            f"print(source.uid, other.uid)"
        )
        source_uid, other_uid = ids.split()
        _shell(
            f"from buddies.services import ProjectService; "
            f"from feusers.models import FeUser; from buddies.models import DummyUser, Project; "
            f"a = FeUser.objects.get(email='{admin['email']}'); c = FeUser.objects.get(email='{carol['email']}'); "
            f"g = Project.objects.get(pk={group_id}); d = DummyUser.objects.get(uid={source_uid}); "
            f"ProjectService.request_group_merge_with_feuser(a, g, d, c)"
        )
        ctx = {"admin": admin, "carol": carol, "group_id": int(group_id), "source_uid": source_uid, "other_uid": other_uid}
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(carol["email"])

    def test_dummy_into_dummy_merge_blocked_while_request_pending(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
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
            "Source member must survive: dummy-into-dummy merge must be rejected while a request is pending"


# ---------------------------------------------------------------------------
# Merging an upfront-payer offline member into another offline member that
# already has an explicit participation row on that same expense: the stale
# row must be dropped, mirroring TestMergeRequestUpfrontPayerBecomesRealOwner
# (in test_merge_request_to_feuser.py) but for the immediate
# dummy-into-dummy path.
# ---------------------------------------------------------------------------

class TestProjectDummyIntoDummyMergeUpfrontPayerConflict:
    """source (offline member) fronted the cash for a project expense. anna
    (offline, 30%) and target (offline, 30%) are explicit participants;
    source's implicit share is 40%. Merging source into target must point
    upfront_payee_dummy at target, remove target's now-stale 30% row, and
    leave only anna's 30% row (target's new implicit share is 70%, not 40%)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Selma", last_name="Conflictadmin")
        group_id = _create_group(admin["email"], "Project Conflict Payer")
        ids = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"source = DummyUser.objects.create(owning_group=g, display_name='Conflict Payer Member'); "
            f"ProjectMember.objects.create(group=g, dummy=source); "
            f"target = DummyUser.objects.create(owning_group=g, display_name='Conflict Target Member'); "
            f"ProjectMember.objects.create(group=g, dummy=target); "
            f"anna = DummyUser.objects.create(owning_group=g, display_name='PAnna Conflict'); "
            f"ProjectMember.objects.create(group=g, dummy=anna); "
            f"print(source.uid, target.uid, anna.uid)"
        )
        source_uid, target_uid, anna_uid = ids.split()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{admin['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"source = DummyUser.objects.get(uid={source_uid}); "
            f"target = DummyUser.objects.get(uid={target_uid}); "
            f"anna = DummyUser.objects.get(uid={anna_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Project Conflict Payer Expense', "
            f"  type='expense', value=Decimal('100.00'), settled=False, buddy_approved=True, project=g, "
            f"  is_dummy=True, upfront_payee_dummy=source); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=target, share_percent=Decimal('30')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=anna, share_percent=Decimal('30')); "
            f"print(e.pk)"
        )
        ctx = {
            "admin": admin, "group_id": int(group_id), "expense_pk": expense_pk.strip(),
            "source_uid": source_uid, "target_uid": target_uid, "anna_uid": anna_uid,
        }
        yield ctx
        cleanup_user(admin["email"])

    def test_admin_merges_source_into_target(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['source_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['source_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"d{ctx['target_uid']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "/settings/" in driver.current_url

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
        assert "Originally paid by: Conflict Payer Member" in note, note

        source_gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['source_uid']}).count())"
        )
        assert source_gone == "0", "Source must be deleted, with no stale references left behind"


# ---------------------------------------------------------------------------
# Cross-scope merge is rejected: a project-scoped offline member can never be
# merged into a personal dummy. The "Merge into..." dropdown never offers
# one (it's built from the project-scope member/dummy lists only), so this
# only matters as a backend guard against a forged request.
# ---------------------------------------------------------------------------

class TestProjectDummyMergeRejectsPersonalScopedTarget:
    """Admin's project_merge_dummy endpoint must reject a target_key
    pointing at a personal dummy, even though the UI never offers one."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Timo", last_name="Crossscopeadmin")
        group_id = _create_group(admin["email"], "Cross Scope Source Project")
        source_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Project Cross Source'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        ).strip()
        personal_dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{admin['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Personal Cross Target'); "
            f"print(d.uid)"
        ).strip()
        ctx = {
            "admin": admin, "group_id": int(group_id),
            "source_uid": source_uid, "personal_dummy_uid": personal_dummy_uid,
        }
        yield ctx
        cleanup_user(admin["email"])

    def test_merge_post_rejected_target_is_personal_scoped(self, driver, w, ctx):
        status = _shell(
            f"from django.test import Client; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['admin']['email']}'); "
            f"c = Client(); s = c.session; s['feuser_id'] = u.pk; s.save(); "
            f"resp = c.post('/projects/{ctx['group_id']}/dummy/{ctx['source_uid']}/merge/', "
            f"  {{'target_key': 'd{ctx['personal_dummy_uid']}'}}); "
            f"print(resp.status_code)"
        ).strip()
        assert status == "404", \
            f"Merging a project-scoped offline member into a personal target must be rejected, got status {status}"

        source_exists = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['source_uid']}).exists())"
        )
        assert source_exists == "True", "Source member must survive a rejected cross-scope merge"

        personal_dummy_untouched = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['personal_dummy_uid']}).exists())"
        )
        assert personal_dummy_untouched == "True", "Personal-scoped target must be untouched"


# ---------------------------------------------------------------------------
# Archived projects block merging, like every other mutation
# ---------------------------------------------------------------------------

class TestArchivedProjectBlocksMerge:
    """An archived project must reject a merge attempt, mirroring how it
    already blocks adding/removing offline members."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Greta", last_name="Owner")
        group_id = _create_group(admin["email"], "Archived Merge Project")
        ids = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d1 = DummyUser.objects.create(owning_group=g, display_name='Archived Source'); "
            f"ProjectMember.objects.create(group=g, dummy=d1); "
            f"d2 = DummyUser.objects.create(owning_group=g, display_name='Archived Target'); "
            f"ProjectMember.objects.create(group=g, dummy=d2); "
            f"g.archived = True; g.save(update_fields=['archived']); "
            f"print(d1.uid, d2.uid)"
        )
        d1_uid, d2_uid = ids.split()
        ctx = {"admin": admin, "group_id": int(group_id), "d1_uid": d1_uid, "d2_uid": d2_uid}
        yield ctx
        cleanup_user(admin["email"])

    def test_merge_post_is_rejected_on_archived_project(self, driver, w, ctx):
        before = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['d1_uid']}).exists())"
        )
        assert before == "True"

        token = _shell(
            f"from django.test import Client; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['admin']['email']}'); "
            f"c = Client(); s = c.session; s['feuser_id'] = u.pk; s.save(); "
            f"resp = c.post('/projects/{ctx['group_id']}/dummy/{ctx['d1_uid']}/merge/', {{'target_key': 'd{ctx['d2_uid']}'}}); "
            f"print(resp.status_code)"
        )
        assert token.strip() == "302", "Should redirect back with an error, not crash"

        after = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['d1_uid']}).exists())"
        )
        assert after == "True", "Source member must survive: merging must be rejected on an archived project"
