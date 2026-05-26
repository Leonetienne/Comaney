"""
Project offline-member self-merge: an admin merges a project's offline
member directly into themselves. Immediate, like dummy-into-dummy merge -
there's no second party to ask. Reuses the same transfer primitives as
accepting a normal merge-into-member request (merge-spec.md: project
self-merge behaves like any other merge), including the owner-exclusion
guard that drops (rather than wrongly creates) a participation row on an
expense the admin already owns.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _confirm, _create_group, _add_group_member, _get_pk


def _settings_url(group_id) -> str:
    return _url(f"/projects/{group_id}/settings/")


# ---------------------------------------------------------------------------
# Admin merges a dummy into themselves: participation on an expense the
# admin already owns is dropped (owner-exclusion); participation on an
# expense owned by someone else is transferred normally.
# ---------------------------------------------------------------------------

class TestProjectSelfMergeParticipant:
    """Admin owns one project expense the dummy participates in, and a
    second project expense (owned by another real member Carol) the dummy
    also participates in. Self-merging the dummy must: drop the row on the
    admin-owned expense (no owner-as-participant row created), and merge
    normally onto the Carol-owned expense (admin becomes an explicit
    participant there, which is valid since admin isn't that expense's
    owner)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Nadia", last_name="Owneradmin")
        carol = setup_user(None, None, first_name="Carol", last_name="Member")
        group_id = _create_group(admin["email"], "Self Merge Project")
        _add_group_member(int(group_id), carol["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Self Merge Member'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        ).strip()
        admin_expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{admin['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Admin Owned Expense', "
            f"  type='expense', value=Decimal('60.00'), settled=False, buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, share_percent=Decimal('25')); "
            f"print(e.pk)"
        ).strip()
        carol_expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"c = FeUser.objects.get(email='{carol['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"e = Expense.objects.create(owning_feuser=c, title='Carol Owned Expense', "
            f"  type='expense', value=Decimal('80.00'), settled=False, buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, share_percent=Decimal('40')); "
            f"print(e.pk)"
        ).strip()
        ctx = {
            "admin": admin, "carol": carol, "group_id": int(group_id), "dummy_uid": dummy_uid,
            "admin_expense_pk": admin_expense_pk, "carol_expense_pk": carol_expense_pk,
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(carol["email"])

    def test_yourself_option_present(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        select_el = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']} select[name='target_key']")
        values = [o.get_attribute("value") for o in select_el.find_elements(By.TAG_NAME, "option")]
        assert "self" in values, "Yourself must be a selectable merge target for the admin"

    def test_admin_merges_dummy_into_self(self, driver, w, ctx):
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value("self")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "/settings/" in driver.current_url

    def test_dummy_gone_member_removed(self, driver, w, ctx):
        gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).count())"
        )
        assert gone == "0", "Dummy must be deleted after self-merge"
        member_gone = _shell(
            f"from buddies.models import ProjectMember; "
            f"print(ProjectMember.objects.filter(dummy_id={ctx['dummy_uid']}).count())"
        )
        assert member_gone == "0", "The dummy's project membership row must be removed"

    def test_admin_owned_expense_row_dropped_not_created(self, driver, w, ctx):
        rows = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['admin_expense_pk']}); "
            f"print(e.buddy_spendings.count())"
        )
        assert rows == "0", \
            "On the expense the admin already owns, the dummy's row must be dropped, not turned into an owner-as-participant row"

    def test_carol_owned_expense_transferred_normally(self, driver, w, ctx):
        rows = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['carol_expense_pk']}); "
            f"print(chr(10).join(f'{{bs.participant_feuser_id}}|{{bs.share_percent}}' for bs in e.buddy_spendings.all()))"
        )
        lines = [l for l in rows.splitlines() if l.strip()]
        assert len(lines) == 1, f"Expected exactly one participant row, got: {lines}"
        feuser_id, share = lines[0].split("|")
        assert feuser_id == _get_pk(ctx["admin"]["email"]), \
            "On an expense owned by someone else, the admin must become the explicit participant"
        assert share == "40.000"


# ---------------------------------------------------------------------------
# Merging an upfront-payer dummy into yourself: you become the real owner
# ---------------------------------------------------------------------------

class TestProjectSelfMergeUpfrontPayer:
    """The dummy fronted the cash for a project expense (is_dummy=True,
    upfront_payee_dummy=dummy). Admin self-merging it makes the admin the
    real owner."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Otto", last_name="Payeradmin")
        group_id = _create_group(admin["email"], "Self Merge Payer Project")
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Self Payer Member'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        ).strip()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import DummyUser, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{admin['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Member Fronted The Cash', "
            f"  type='expense', value=Decimal('45.00'), settled=False, buddy_approved=True, project=g, "
            f"  is_dummy=True, upfront_payee_dummy=d); "
            f"print(e.pk)"
        ).strip()
        ctx = {"admin": admin, "group_id": int(group_id), "dummy_uid": dummy_uid, "expense_pk": expense_pk}
        yield ctx
        cleanup_user(admin["email"])

    def test_admin_merges_dummy_into_self(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
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
        assert owning_feuser_id == _get_pk(ctx["admin"]["email"])
        assert is_dummy == "False"
        assert upfront_payee_dummy_id == "None"


# ---------------------------------------------------------------------------
# Self-merge is blocked while an outgoing merge request is pending for that
# dummy, same as the immediate dummy-into-dummy path
# ---------------------------------------------------------------------------

class TestProjectSelfMergeBlockedWhilePending:
    """Admin sent a merge request for the dummy to another real project
    member; self-merging the same dummy before they respond must be
    rejected."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Petra", last_name="Pendingadmin")
        carol = setup_user(None, None, first_name="Carol", last_name="Pendingmember")
        group_id = _create_group(admin["email"], "Self Merge Pending Project")
        _add_group_member(int(group_id), carol["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Self Pending Member'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        ).strip()
        _shell(
            f"from buddies.services import ProjectService; "
            f"from feusers.models import FeUser; from buddies.models import DummyUser, Project; "
            f"a = FeUser.objects.get(email='{admin['email']}'); c = FeUser.objects.get(email='{carol['email']}'); "
            f"g = Project.objects.get(pk={group_id}); d = DummyUser.objects.get(uid={dummy_uid}); "
            f"ProjectService.request_group_merge_with_feuser(a, g, d, c)"
        )
        ctx = {"admin": admin, "carol": carol, "group_id": int(group_id), "dummy_uid": dummy_uid}
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(carol["email"])

    def test_self_merge_blocked_while_request_pending(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
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
