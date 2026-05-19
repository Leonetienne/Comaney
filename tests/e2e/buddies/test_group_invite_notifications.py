"""
Group invite accept/decline: invitor receives email notification.
Group dummy merge for non-registered users: onboarding email mentions the group.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, setup_user, cleanup_user,
    fetch_email, extract_link, mailpit_seen_ids,
)
from bhelpers import _shell, _login_as, _create_group


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
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import BuddyGroup; "
            f"admin = FeUser.objects.get(email='{a['email']}'); "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
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
        driver.find_element(By.ID, "btn-accept-group-invite").click()
        time.sleep(1)
        assert "/buddies/groups/" in driver.current_url

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
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import BuddyGroup; "
            f"admin = FeUser.objects.get(email='{a['email']}'); "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
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
        driver.find_element(By.ID, "btn-decline-group-invite").click()
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
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import BuddyGroup; "
            f"admin = FeUser.objects.get(email='{a['email']}'); "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
            f"d = BuddyGroupService.create_group_dummy(g, admin, 'Offline Gary'); "
            f"print(d.uid)"
        )
        yield {"a": a, "group_id": int(group_id), "dummy_uid": dummy_uid.strip()}
        cleanup_user(a["email"])

    def test_onboarding_invite_email_mentions_group(self, driver, w, ctx):
        target_email = f"newuser-{ctx['dummy_uid']}@example.test"
        seen_before = mailpit_seen_ids()
        _shell(
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; "
            f"from buddies.models import BuddyGroup, DummyUser; "
            f"admin = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"g = BuddyGroup.objects.get(pk={ctx['group_id']}); "
            f"d = DummyUser.objects.get(uid='{ctx['dummy_uid']}'); "
            f"BuddyGroupService.send_group_dummy_merge_invite(g, admin, d, '{target_email}')"
        )
        body = fetch_email(target_email, "invited you to join their group", ignore_ids=seen_before)
        assert "Merge Notify Group" in body
        assert "Offline Gary" in body
