"""
Dummy-merge accept/decline mechanics: personal dummy merge and group dummy merge.

Invites here are seeded directly via shell rather than driven through the UI;
see test_merge_request_to_feuser.py and test_dummy_merge_into_dummy.py for the
UI-driven "Merge into..." flows that replaced the old free-text-email form.

Personal merge: A has a dummy; an invite to B is seeded; B accepts or declines.
Group merge: Admin has a group dummy; an invite to C is seeded; C accepts.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_group, _add_group_member, _create_buddy_link


# ---------------------------------------------------------------------------
# Personal dummy merge: B accepts
# ---------------------------------------------------------------------------

class TestPersonalDummyMergeAccept:
    """A has a dummy 'Merge Buddy'; A sends merge invite to B; B accepts."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Alice", last_name="Merger")
        b = setup_user(None, None, first_name="Bob", last_name="Mergee")
        # A merge target must already be a buddy (request_merge_with_feuser's
        # "not_linked" precondition); link them before seeding the invite.
        _create_buddy_link(a["email"], b["email"])
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Merge Buddy'); "
            f"print(d.uid)"
        )
        # Create an expense for A where the dummy is participant; must transfer to B after merge
        _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"import datetime; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.get(uid='{dummy_uid.strip()}'); "
            f"e = Expense.objects.create(owning_feuser=u, title='Merge History Expense', "
            f"  type='expense', value=Decimal('100.00'), "
            f"  date_due=datetime.date.today(), settled=False, buddy_approved=True); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, "
            f"  share_percent=Decimal('50'))"
        )
        ctx = {"a": a, "b": b, "dummy_uid": dummy_uid.strip()}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_sends_merge_invite(self, driver, w, ctx):
        # The UI can no longer target a not-yet-linked stranger directly (see
        # test_merge_request_to_feuser.py for the UI-driven, already-linked flow);
        # seed the invite directly to exercise the accept-side mechanics below.
        token = _shell(
            f"from buddies.models import DummyUser, DummyMergeInvite; "
            f"from feusers.models import FeUser; "
            f"import datetime; "
            f"from django.utils import timezone; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"dummy = DummyUser.objects.get(uid='{ctx['dummy_uid']}'); "
            f"inv = DummyMergeInvite.objects.create("
            f"  inviting_feuser=a, dummy=dummy, invited_feuser=b, "
            f"  expires_at=timezone.now() + datetime.timedelta(days=7)); "
            f"print(inv.token)"
        )
        ctx["merge_link"] = _url(f"/buddies/merge/{token.strip()}/")

    def test_b_sees_merge_invite_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(ctx["merge_link"])
        time.sleep(1)
        assert "Merge Buddy" in driver.page_source
        assert "Accept and merge" in driver.page_source

    def test_b_accepts_merge(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_b_sees_a_as_buddy_after_merge(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert ctx["a"]["email"] in driver.page_source

    def test_b_sees_transferred_expense_on_summary(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Merge History Expense" in driver.page_source, \
            "Expense previously tracked under the dummy must transfer to B after merge"

    def test_a_sees_b_not_dummy_after_merge(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert ctx["b"]["email"] in driver.page_source, \
            "After merge, A must see B as a real buddy"
        assert "Merge Buddy" not in driver.page_source, \
            "The dummy must be gone after merge"


# ---------------------------------------------------------------------------
# Personal dummy merge: B declines
# ---------------------------------------------------------------------------

class TestPersonalDummyMergeDecline:
    """A has a dummy; merge invite is sent via shell; B declines."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Dana", last_name="Decliner")
        b = setup_user(None, None, first_name="Eve", last_name="Decliner")
        # Create dummy and merge invite via shell to avoid email overhead
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Decline Dummy'); "
            f"print(d.uid)"
        )
        token = _shell(
            f"from buddies.models import DummyUser, DummyMergeInvite; "
            f"from feusers.models import FeUser; "
            f"import uuid; "
            f"from django.utils import timezone; "
            f"import datetime; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            f"dummy = DummyUser.objects.get(uid='{dummy_uid.strip()}'); "
            f"inv = DummyMergeInvite.objects.create("
            f"  inviting_feuser=a, dummy=dummy, invited_feuser=b, "
            f"  expires_at=timezone.now() + datetime.timedelta(days=7)); "
            f"print(inv.token)"
        )
        ctx = {"a": a, "b": b, "token": token.strip(), "dummy_uid": dummy_uid.strip()}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_b_sees_merge_invite_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/buddies/merge/{ctx['token']}/"))
        time.sleep(1)
        assert "Decline Dummy" in driver.page_source
        assert "Decline" in driver.page_source

    def test_b_declines_merge(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-decline-merge").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_no_buddy_link_after_decline(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import BuddyLink; "
            f"from feusers.models import FeUser; "
            f"from django.db.models import Q; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(BuddyLink.objects.filter(Q(user_a=a,user_b=b)|Q(user_a=b,user_b=a)).count())"
        )
        assert count == "0", "No BuddyLink must exist after decline"

    def test_dummy_still_exists_for_a(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Decline Dummy" in driver.page_source, \
            "Dummy must still be present on A's page after B declines"


# ---------------------------------------------------------------------------
# Group dummy merge: C accepts
# ---------------------------------------------------------------------------

class TestGroupDummyMergeAccept:
    """Admin sends merge invite for a group dummy to existing member C; C accepts
    and the dummy's history is linked to C's real account."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Greg", last_name="GroupAdmin")
        c = setup_user(None, None, first_name="Clara", last_name="GroupJoiner")
        group_id = _create_group(admin["email"], "MergeGroup")
        # A merge target must already be a project member
        # (request_group_merge_with_feuser's "not_member" precondition).
        _add_group_member(int(group_id), c["email"])
        # Add a group dummy
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, BuddyGroupMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Group Dummy'); "
            f"BuddyGroupMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        ctx = {
            "admin": admin, "c": c,
            "group_id": group_id,
            "dummy_uid": dummy_uid.strip(),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(c["email"])

    def test_admin_sends_group_merge_invite(self, driver, w, ctx):
        # The UI can no longer target a not-yet-linked stranger directly (see
        # test_merge_request_to_feuser.py for the UI-driven, already-member flow);
        # seed the invite directly to exercise the accept-side mechanics below.
        token = _shell(
            f"from buddies.models import DummyUser, DummyMergeInvite; "
            f"from feusers.models import FeUser; "
            f"import datetime; "
            f"from django.utils import timezone; "
            f"admin = FeUser.objects.get(email='{ctx['admin']['email']}'); "
            f"c = FeUser.objects.get(email='{ctx['c']['email']}'); "
            f"dummy = DummyUser.objects.get(uid='{ctx['dummy_uid']}'); "
            f"inv = DummyMergeInvite.objects.create("
            f"  inviting_feuser=admin, dummy=dummy, invited_feuser=c, "
            f"  expires_at=timezone.now() + datetime.timedelta(days=7)); "
            f"print(inv.token)"
        )
        ctx["merge_link"] = _url(f"/buddies/merge/{token.strip()}/")

    def test_c_sees_group_merge_page(self, driver, w, ctx):
        _login_as(driver, ctx["c"])
        driver.get(ctx["merge_link"])
        time.sleep(1)
        assert "MergeGroup" in driver.page_source
        assert "Group Dummy" in driver.page_source
        assert "Accept and merge" in driver.page_source

    def test_c_accepts_group_merge(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert f"/projects/{ctx['group_id']}/" in driver.current_url, \
            "Accepting a group merge must land on the project, not My Buddies"

    def test_c_is_member_after_merge(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert ctx["c"]["email"] in driver.page_source or \
               "Clara GroupJoiner" in driver.page_source, \
            "C must appear as a group member after accepting the group merge"

    def test_group_dummy_gone_after_merge(self, driver, w, ctx):
        assert "Group Dummy" not in driver.page_source, \
            "The group dummy must be replaced by C's real account after merge"


# ---------------------------------------------------------------------------
# Personal dummy merge: accept fails after the buddies have un-buddied
# ---------------------------------------------------------------------------

class TestPersonalMergeAcceptAfterUnbuddy:
    """A request is sent while A and B are buddies; they un-buddy before B
    accepts. Accepting must fail cleanly rather than silently re-creating the
    BuddyLink A and B deliberately removed."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Uma", last_name="Unbuddied")
        b = setup_user(None, None, first_name="Bert", last_name="Unbuddied")
        _create_buddy_link(a["email"], b["email"])
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Stale Merge Buddy'); "
            f"print(d.uid)"
        )
        token = _shell(
            f"from buddies.models import DummyUser, DummyMergeInvite; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            f"dummy = DummyUser.objects.get(uid='{dummy_uid.strip()}'); "
            f"inv = DummyMergeInvite.objects.create("
            f"  inviting_feuser=a, dummy=dummy, invited_feuser=b); "
            f"print(inv.token)"
        )
        # A and B un-buddy after the request was sent, but before B accepts.
        _shell(
            f"from buddies.services import BuddyLifecycleService; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            f"BuddyLifecycleService.kick_actual(a, b, has_debt_warning_accepted=True)"
        )
        ctx = {
            "a": a, "b": b,
            "dummy_uid": dummy_uid.strip(),
            "merge_link": _url(f"/buddies/merge/{token.strip()}/"),
        }
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_b_accept_is_rejected_after_unbuddy(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(ctx["merge_link"])
        time.sleep(1)
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "invalid or has expired" in driver.page_source, \
            "Accepting after un-buddying must fail cleanly, not re-link them"

    def test_no_buddy_link_recreated(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import BuddyLink; "
            f"from feusers.models import FeUser; "
            f"from django.db.models import Q; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(BuddyLink.objects.filter(Q(user_a=a,user_b=b)|Q(user_a=b,user_b=a)).count())"
        )
        assert count == "0", "Accepting a stale request must not re-create the BuddyLink"

    def test_dummy_still_present_for_a(self, driver, w, ctx):
        exists = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).exists())"
        )
        assert exists == "True", "The dummy must survive a rejected accept"


# ---------------------------------------------------------------------------
# Group dummy merge: accept fails after the member left the project
# ---------------------------------------------------------------------------

class TestProjectMergeAcceptAfterLeave:
    """Admin sends a merge request for a group dummy to member M; M leaves the
    project before accepting. Accepting must fail cleanly rather than
    re-adding M as a member of a project they left."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Mona", last_name="Owner")
        m = setup_user(None, None, first_name="Milo", last_name="Leaver")
        group_id = _create_group(admin["email"], "Leave Then Merge Project")
        _add_group_member(int(group_id), m["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Stale Group Dummy'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        token = _shell(
            f"from buddies.models import DummyUser, DummyMergeInvite; "
            f"from feusers.models import FeUser; "
            f"admin = FeUser.objects.get(email='{admin['email']}'); "
            f"m = FeUser.objects.get(email='{m['email']}'); "
            f"dummy = DummyUser.objects.get(uid='{dummy_uid.strip()}'); "
            f"inv = DummyMergeInvite.objects.create("
            f"  inviting_feuser=admin, dummy=dummy, invited_feuser=m); "
            f"print(inv.token)"
        )
        # M leaves the project after the request was sent, but before accepting.
        _shell(
            f"from buddies.services import ProjectService; "
            f"from buddies.models import Project, ProjectMember; "
            f"from feusers.models import FeUser; "
            f"g = Project.objects.get(pk={group_id}); "
            f"admin = FeUser.objects.get(email='{admin['email']}'); "
            f"m = FeUser.objects.get(email='{m['email']}'); "
            f"pm = ProjectMember.objects.get(group=g, feuser=m); "
            f"ProjectService.remove_member(g, admin, pm, notify=False)"
        )
        ctx = {
            "admin": admin, "m": m,
            "group_id": int(group_id),
            "dummy_uid": dummy_uid.strip(),
            "merge_link": _url(f"/buddies/merge/{token.strip()}/"),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(m["email"])

    def test_m_accept_is_rejected_after_leaving(self, driver, w, ctx):
        _login_as(driver, ctx["m"])
        driver.get(ctx["merge_link"])
        time.sleep(1)
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "invalid or has expired" in driver.page_source, \
            "Accepting after leaving the project must fail cleanly, not re-add M"

    def test_m_not_readded_as_member(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import ProjectMember; "
            f"from feusers.models import FeUser; "
            f"m = FeUser.objects.get(email='{ctx['m']['email']}'); "
            f"print(ProjectMember.objects.filter(group_id={ctx['group_id']}, feuser=m).count())"
        )
        assert count == "0", "M must not be re-added as a project member"

    def test_group_dummy_still_present(self, driver, w, ctx):
        exists = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).exists())"
        )
        assert exists == "True", "The dummy must survive a rejected accept"


# ---------------------------------------------------------------------------
# Group dummy merge: accept fails after the project was archived
# ---------------------------------------------------------------------------

class TestProjectMergeAcceptAfterArchive:
    """Admin sends a merge request for a group dummy to member M; the project
    is archived before M accepts. Accepting must fail cleanly rather than
    mutating an archived project."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Aria", last_name="Owner")
        m = setup_user(None, None, first_name="Max", last_name="Member")
        group_id = _create_group(admin["email"], "Archive Then Merge Project")
        _add_group_member(int(group_id), m["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Archived Stale Dummy'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        token = _shell(
            f"from buddies.models import DummyUser, DummyMergeInvite; "
            f"from feusers.models import FeUser; "
            f"admin = FeUser.objects.get(email='{admin['email']}'); "
            f"m = FeUser.objects.get(email='{m['email']}'); "
            f"dummy = DummyUser.objects.get(uid='{dummy_uid.strip()}'); "
            f"inv = DummyMergeInvite.objects.create("
            f"  inviting_feuser=admin, dummy=dummy, invited_feuser=m); "
            f"print(inv.token)"
        )
        # The project is archived after the request was sent, but before accepting.
        _shell(
            f"from buddies.models import Project; "
            f"g = Project.objects.get(pk={group_id}); "
            f"g.archived = True; g.save(update_fields=['archived'])"
        )
        ctx = {
            "admin": admin, "m": m,
            "group_id": int(group_id),
            "dummy_uid": dummy_uid.strip(),
            "merge_link": _url(f"/buddies/merge/{token.strip()}/"),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(m["email"])

    def test_m_accept_is_rejected_on_archived_project(self, driver, w, ctx):
        _login_as(driver, ctx["m"])
        driver.get(ctx["merge_link"])
        time.sleep(1)
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "invalid or has expired" in driver.page_source, \
            "Accepting on an archived project must fail cleanly, not mutate it"

    def test_dummy_member_row_untouched(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import ProjectMember; "
            f"print(ProjectMember.objects.filter(group_id={ctx['group_id']}, dummy_id={ctx['dummy_uid']}).count())"
        )
        assert count == "1", "The dummy's ProjectMember row must survive a rejected accept"

    def test_dummy_still_present(self, driver, w, ctx):
        exists = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).exists())"
        )
        assert exists == "True", "The dummy must survive a rejected accept"
