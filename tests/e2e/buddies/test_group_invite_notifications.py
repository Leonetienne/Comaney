"""
Group invite accept/decline: invitor receives email notification.
Group dummy merge for non-registered users: onboarding email mentions the group.
Group member removal: removed member receives email notification.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, setup_user, cleanup_user,
    fetch_email, extract_link, mailpit_seen_ids,
)
from bhelpers import _shell, _login_as, _create_group, _add_group_member, _confirm


# ---------------------------------------------------------------------------
# Invitor notified when invitee accepts group invite
# ---------------------------------------------------------------------------

class TestGroupInviteAcceptNotifiesAdmin:
    """Admin invites C; C accepts; admin receives a notification email."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Notify", last_name="Admin")
        c = setup_user(None, None, first_name="Accept", last_name="Notif")
        group_id = _create_group(a["email"], "Notify Accept Group")
        seen_before = mailpit_seen_ids()
        _shell(
            f"from buddies.services import ProjectService; "
            f"from feusers.models import FeUser; from buddies.models import Project; "
            f"admin = FeUser.objects.get(email='{a['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"BuddyGroupService.invite_member(g, admin, '{c['email']}')"
        )
        body = fetch_email(c["email"], "Notify Accept Group", ignore_ids=seen_before)
        invite_link = extract_link(body)
        yield {"a": a, "c": c, "group_id": int(group_id), "invite_link": invite_link}
        cleanup_user(a["email"])
        cleanup_user(c["email"])

    def test_c_accepts_group_invite(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_accept"] = seen_before
        _login_as(driver, ctx["c"])
        driver.get(ctx["invite_link"])
        time.sleep(1)
        driver.find_element(By.ID, "btn-accept-project-invite").click()
        time.sleep(1)
        assert "/projects/" in driver.current_url

    def test_admin_receives_accepted_notification(self, driver, w, ctx):
        body = fetch_email(
            ctx["a"]["email"],
            "joined your group",
            ignore_ids=ctx["seen_before_accept"],
        )
        assert "Notify Accept Group" in body
        assert "Accept" in body or "Notif" in body


# ---------------------------------------------------------------------------
# Invitor notified when invitee declines group invite
# ---------------------------------------------------------------------------

class TestGroupInviteDeclineNotifiesAdmin:
    """Admin invites C; C declines; admin receives a notification email."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="DecNotify", last_name="Admin")
        c = setup_user(None, None, first_name="Decline", last_name="Notif")
        group_id = _create_group(a["email"], "Notify Decline Group")
        seen_before = mailpit_seen_ids()
        _shell(
            f"from buddies.services import ProjectService; "
            f"from feusers.models import FeUser; from buddies.models import Project; "
            f"admin = FeUser.objects.get(email='{a['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"BuddyGroupService.invite_member(g, admin, '{c['email']}')"
        )
        body = fetch_email(c["email"], "Notify Decline Group", ignore_ids=seen_before)
        invite_link = extract_link(body)
        yield {"a": a, "c": c, "group_id": int(group_id), "invite_link": invite_link}
        cleanup_user(a["email"])
        cleanup_user(c["email"])

    def test_c_declines_group_invite(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_decline"] = seen_before
        _login_as(driver, ctx["c"])
        driver.get(ctx["invite_link"])
        time.sleep(1)
        driver.find_element(By.ID, "btn-decline-project-invite").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_admin_receives_declined_notification(self, driver, w, ctx):
        body = fetch_email(
            ctx["a"]["email"],
            "declined your invitation",
            ignore_ids=ctx["seen_before_decline"],
        )
        assert "Notify Decline Group" in body
        assert "Decline" in body or "Notif" in body


# ---------------------------------------------------------------------------
# Group dummy merge onboarding email mentions the group name
# ---------------------------------------------------------------------------

class TestGroupDummyMergeOnboardingEmailMentionsGroup:
    """Admin sends merge invite for a group dummy to an unregistered email.
    The onboarding email must mention the group name."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Merge", last_name="Admin")
        group_id = _create_group(a["email"], "Merge Notify Group")
        dummy_uid = _shell(
            f"from buddies.services import ProjectService; "
            f"from feusers.models import FeUser; from buddies.models import Project; "
            f"admin = FeUser.objects.get(email='{a['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = BuddyGroupService.create_group_dummy(g, admin, 'Offline Gary'); "
            f"print(d.uid)"
        )
        yield {"a": a, "group_id": int(group_id), "dummy_uid": dummy_uid.strip()}
        cleanup_user(a["email"])

    def test_onboarding_invite_email_mentions_group(self, driver, w, ctx):
        target_email = f"newuser-{ctx['dummy_uid']}@example.test"
        seen_before = mailpit_seen_ids()
        _shell(
            f"from buddies.services import ProjectService; "
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project, DummyUser; "
            f"admin = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"g = Project.objects.get(pk={ctx['group_id']}); "
            f"d = DummyUser.objects.get(uid='{ctx['dummy_uid']}'); "
            f"BuddyGroupService.send_group_dummy_merge_invite(g, admin, d, '{target_email}')"
        )
        body = fetch_email(target_email, "invited you to join their group", ignore_ids=seen_before)
        assert "Merge Notify Group" in body
        assert "Offline Gary" in body


# ---------------------------------------------------------------------------
# Admin removes a member: removed member receives email notification
# ---------------------------------------------------------------------------

class TestGroupMemberRemovedNotification:
    """Admin removes a member; removed member receives a removal notification email."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Remove", last_name="Admin")
        b = setup_user(None, None, first_name="Removed", last_name="Member")
        group_id = _create_group(a["email"], "Remove Notify Group")
        _add_group_member(int(group_id), b["email"])
        yield {"a": a, "b": b, "group_id": int(group_id)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_admin_removes_member(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_remove"] = seen_before
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        # Find and click the remove button for member b
        member_pk = _shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import ProjectMember, BuddyGroup; "
            f"g = Project.objects.get(pk={ctx['group_id']}); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(BuddyGroupMember.objects.get(group=g, feuser=b).uid)"
        ).strip()
        driver.find_element(By.ID, f"btn-remove-member-{member_pk}").click()
        time.sleep(0.5)
        _confirm(driver)

    def test_removed_member_receives_email(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"],
            "removed from the group",
            ignore_ids=ctx["seen_before_remove"],
        )
        assert "Remove Notify Group" in body
        assert "Remove" in body or "Admin" in body

    def test_voluntary_leave_sends_no_email(self, driver, w, ctx):
        """A member who leaves voluntarily must NOT receive a removal email."""
        c = setup_user(None, None, first_name="Leaving", last_name="Voluntarily")
        _add_group_member(ctx["group_id"], c["email"])
        seen_before = mailpit_seen_ids()
        _shell(
            f"from buddies.services import ProjectService; "
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project, BuddyGroupMember; "
            f"g = Project.objects.get(pk={ctx['group_id']}); "
            f"c = FeUser.objects.get(email='{c['email']}'); "
            f"m = BuddyGroupMember.objects.get(group=g, feuser=c); "
            f"BuddyGroupService.remove_member(g, g.admin_feuser, m, notify=False)"
        )
        import time as _time
        _time.sleep(3)
        try:
            fetch_email(c["email"], "removed from the group", timeout=5, ignore_ids=seen_before)
            assert False, "Voluntary leave must not send a removal email"
        except TimeoutError:
            pass  # expected: no email sent
        cleanup_user(c["email"])
