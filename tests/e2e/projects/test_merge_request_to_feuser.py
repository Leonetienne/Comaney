"""
Project offline-member-into-real-member merge requests: requires the target's approval.
Only an existing project member can be selected as a target. The pending request is
surfaced on the project's settings page, not on My Buddies.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user, fetch_email, extract_link, mailpit_seen_ids
from bhelpers import _shell, _login_as, _confirm, _create_group, _add_group_member, _get_pk


def _settings_url(group_id) -> str:
    return _url(f"/projects/{group_id}/settings/")


class TestProjectMergeRequestAcceptFlow:
    """Admin requests merging a project offline member into an existing (non-admin) member."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Jonas", last_name="Owner")
        member = setup_user(None, None, first_name="Kira", last_name="Member")
        group_id = _create_group(admin["email"], "Merge Request Project")
        _add_group_member(int(group_id), member["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Project Request Dummy'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        dummy_uid = dummy_uid.strip()
        _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{admin['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Project Request Expense', "
            f"  type='expense', value=Decimal('55.00'), settled=False, buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, share_percent=Decimal('50'))"
        )
        ctx = {
            "admin": admin, "member": member, "group_id": int(group_id),
            "dummy_uid": dummy_uid, "member_pk": _get_pk(member["email"]),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_admin_sends_merge_request_to_member(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['member_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "Merge request sent" in driver.page_source

    def test_merge_request_email_arrives(self, driver, w, ctx):
        body = fetch_email(
            ctx["member"]["email"],
            "merge an offline member's history",
            ignore_ids=ctx.get("seen_before"),
        )
        ctx["merge_link"] = extract_link(body)
        assert "/buddies/merge/" in ctx["merge_link"]

    def test_member_sees_pending_card_on_project_settings_not_my_buddies(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        assert "Merge requests for you" in driver.page_source
        assert "Project Request Dummy" in driver.page_source

        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert "Project Request Dummy" not in driver.page_source, \
            "Project-scoped merge requests must not appear on My Buddies"

    def test_member_accepts_merge_request(self, driver, w, ctx):
        driver.get(ctx["merge_link"])
        time.sleep(1)
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert f"/projects/{ctx['group_id']}/" in driver.current_url, \
            "Accepting a project merge request must land on the project, not My Buddies"
        assert "is now linked to your account" in driver.page_source

    def test_dummy_gone_no_duplicate_member_history_transferred(self, driver, w, ctx):
        gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).count())"
        )
        assert gone == "0"
        member_count = _shell(
            f"from buddies.models import Project, ProjectMember; from feusers.models import FeUser; "
            f"g = Project.objects.get(pk={ctx['group_id']}); "
            f"u = FeUser.objects.get(email='{ctx['member']['email']}'); "
            f"print(ProjectMember.objects.filter(group=g, feuser=u).count())"
        )
        assert member_count == "1", "Accepting must not create a duplicate ProjectMember"
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Project Request Expense" in driver.page_source


# ---------------------------------------------------------------------------
# Regression: merge target already owns one of the dummy's expenses
# ---------------------------------------------------------------------------

class TestProjectMergeRequestTargetIsExpenseOwner:
    """
    The merge target can already be the payer of an expense the dummy
    participated in (e.g. admin sends the merge request, but the expense
    itself was paid by the member being merged into). The expense owner
    must never end up as an explicit BuddySpending participant on their
    own expense - transfer_dummy_participation_to_feuser must drop that
    row instead of reassigning it.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Petra", last_name="Admin")
        member = setup_user(None, None, first_name="Otto", last_name="Owner")
        group_id = _create_group(admin["email"], "Owner Target Merge Project")
        _add_group_member(int(group_id), member["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Owner Target Dummy'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        dummy_uid = dummy_uid.strip()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"m = FeUser.objects.get(email='{member['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"e = Expense.objects.create(owning_feuser=m, title='Owner Target Expense', "
            f"  type='expense', value=Decimal('80.00'), settled=False, buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, share_percent=Decimal('40')); "
            f"print(e.pk)"
        )
        ctx = {
            "admin": admin, "member": member, "group_id": int(group_id),
            "dummy_uid": dummy_uid, "member_pk": _get_pk(member["email"]),
            "expense_pk": expense_pk.strip(),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_admin_sends_merge_request_to_expense_owner(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['member_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "Merge request sent" in driver.page_source

    def test_member_accepts_merge_request(self, driver, w, ctx):
        body = fetch_email(
            ctx["member"]["email"],
            "merge an offline member's history",
            ignore_ids=ctx.get("seen_before"),
        )
        merge_link = extract_link(body)
        _login_as(driver, ctx["member"])
        driver.get(merge_link)
        time.sleep(1)
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "is now linked to your account" in driver.page_source

    def test_no_stale_owner_as_participant_row(self, driver, w, ctx):
        """The expense owner must never end up as an explicit BuddySpending participant."""
        stale_count = _shell(
            f"from buddies.models import BuddySpending; "
            f"print(BuddySpending.objects.filter(expense_id={ctx['expense_pk']}, "
            f"  participant_feuser_id={ctx['member_pk']}).count())"
        )
        assert stale_count == "0", \
            "Merging a dummy into the expense's own owner must drop the row, not reassign it"

        remaining_participants = _shell(
            f"from buddies.models import BuddySpending; "
            f"print(BuddySpending.objects.filter(expense_id={ctx['expense_pk']}).count())"
        )
        assert remaining_participants == "0", \
            "The dummy's old share must be fully absorbed by the owner's implicit share"

    def test_expense_and_member_untouched_otherwise(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Owner Target Expense" in driver.page_source
        member_count = _shell(
            f"from buddies.models import Project, ProjectMember; from feusers.models import FeUser; "
            f"g = Project.objects.get(pk={ctx['group_id']}); "
            f"u = FeUser.objects.get(email='{ctx['member']['email']}'); "
            f"print(ProjectMember.objects.filter(group=g, feuser=u).count())"
        )
        assert member_count == "1", "Accepting must not create a duplicate ProjectMember"


# ---------------------------------------------------------------------------
# Admin can revoke an outgoing project merge request before the target responds
# ---------------------------------------------------------------------------

class TestProjectMergeRequestRevoke:
    """Admin sends a merge request to a member; admin revokes it before they respond."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Bram", last_name="Owner")
        member = setup_user(None, None, first_name="Cleo", last_name="Pending")
        group_id = _create_group(admin["email"], "Revoke Merge Project")
        _add_group_member(int(group_id), member["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Revoke Project Dummy'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        ctx = {
            "admin": admin, "member": member, "group_id": int(group_id),
            "dummy_uid": dummy_uid.strip(), "member_pk": _get_pk(member["email"]),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_admin_sends_request(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['member_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)

    def test_admin_sees_sent_request_and_revokes(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        assert "Merge requests sent" in driver.page_source
        assert "Revoke Project Dummy" in driver.page_source
        token = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['dummy_uid']}); "
            f"print(DummyMergeInvite.objects.get(dummy=d).token)"
        ).strip()
        driver.find_element(By.ID, f"btn-revoke-merge-{token}").click()
        time.sleep(1)
        assert "/settings/" in driver.current_url

    def test_invite_gone_dummy_untouched(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['dummy_uid']}); "
            f"print(DummyMergeInvite.objects.filter(dummy=d).count())"
        )
        assert count == "0", "Revoked invite must be gone"
        exists = _shell(
            f"from buddies.models import DummyUser; print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).exists())"
        )
        assert exists == "True", "Dummy must still exist after revoke, untouched"


# ---------------------------------------------------------------------------
# A second merge request for the same project dummy is blocked while pending
# ---------------------------------------------------------------------------

class TestProjectMergeRequestBlocksDuplicate:
    """Admin sends a merge request to one member; sending another for the same
    dummy to a different member must be blocked until the first is resolved."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Dario", last_name="Owner")
        memberB = setup_user(None, None, first_name="Elin", last_name="FirstTarget")
        memberC = setup_user(None, None, first_name="Finn", last_name="SecondTarget")
        group_id = _create_group(admin["email"], "Duplicate Merge Project")
        _add_group_member(int(group_id), memberB["email"])
        _add_group_member(int(group_id), memberC["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Duplicate Project Dummy'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        ctx = {
            "admin": admin, "memberB": memberB, "memberC": memberC, "group_id": int(group_id),
            "dummy_uid": dummy_uid.strip(),
            "b_pk": _get_pk(memberB["email"]), "c_pk": _get_pk(memberC["email"]),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(memberB["email"])
        cleanup_user(memberC["email"])

    def test_first_request_succeeds(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['b_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "Merge request sent" in driver.page_source

    def test_second_request_is_blocked(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['c_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "pending merge request" in driver.page_source.lower()
        count = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['dummy_uid']}); "
            f"print(DummyMergeInvite.objects.filter(dummy=d).count())"
        )
        assert count == "1", "Only the first invite must exist"


# ---------------------------------------------------------------------------
# Declining a project merge request from the project settings page must land
# back on the project, not on My Buddies (same pitfall as accepting).
# ---------------------------------------------------------------------------

class TestProjectMergeRequestDeclineFlow:
    """Admin requests a merge; the member declines from the project settings
    page. Dummy stays with the project, member's existing membership untouched."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Hugo", last_name="Owner")
        member = setup_user(None, None, first_name="Ines", last_name="Decliner")
        group_id = _create_group(admin["email"], "Decline Merge Project")
        _add_group_member(int(group_id), member["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Decline Project Dummy'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        ctx = {
            "admin": admin, "member": member, "group_id": int(group_id),
            "dummy_uid": dummy_uid.strip(), "member_pk": _get_pk(member["email"]),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_admin_sends_request(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['member_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)

    def test_member_declines_from_project_settings(self, driver, w, ctx):
        token = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['dummy_uid']}); "
            f"print(DummyMergeInvite.objects.get(dummy=d).token)"
        ).strip()
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"btn-decline-merge-{token}").click()
        time.sleep(1)
        assert f"/projects/{ctx['group_id']}/" in driver.current_url, \
            "Declining a project merge request must land on the project, not My Buddies"

    def test_dummy_and_membership_untouched(self, driver, w, ctx):
        exists = _shell(
            f"from buddies.models import DummyUser; print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).exists())"
        )
        assert exists == "True", "Dummy must stay with the project after a decline"
        member_count = _shell(
            f"from buddies.models import Project, ProjectMember; from feusers.models import FeUser; "
            f"g = Project.objects.get(pk={ctx['group_id']}); "
            f"u = FeUser.objects.get(email='{ctx['member']['email']}'); "
            f"print(ProjectMember.objects.filter(group=g, feuser=u).count())"
        )
        assert member_count == "1", "Member's existing membership must be untouched by the decline"


# ---------------------------------------------------------------------------
# A pending incoming merge request must show as a red badge on the project's
# card in the project list, not just in the sidebar/navbar counters.
# ---------------------------------------------------------------------------

class TestProjectMergeRequestShowsBadgeOnProjectCard:
    """The recipient's /projects/ list shows an action-badge on the project
    card while a merge request for that project is pending."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Jonah", last_name="Owner")
        member = setup_user(None, None, first_name="Kayla", last_name="Member")
        group_id = _create_group(admin["email"], "Card Badge Merge Project")
        _add_group_member(int(group_id), member["email"])
        dummy_uid = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Card Badge Dummy'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        ctx = {
            "admin": admin, "member": member, "group_id": int(group_id),
            "dummy_uid": dummy_uid.strip(), "member_pk": _get_pk(member["email"]),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_admin_sends_request(self, driver, w, ctx):
        driver.get(_settings_url(ctx["group_id"]))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['member_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)

    def test_member_sees_badge_on_project_card(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url("/projects/"))
        time.sleep(1)
        card_name_el = driver.find_element(
            By.XPATH, "//span[contains(@class,'bgs-name') and contains(.,'Card Badge Merge Project')]"
        )
        assert card_name_el.find_elements(By.CSS_SELECTOR, ".action-badge"), \
            "Project card must show the action-badge while a merge request is pending"
