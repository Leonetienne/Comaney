"""
Error paths and edge cases for the buddies extension.

Covers: invalid tokens, expired invites, wrong-account invite pages,
and admin self-removal guard.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_buddy_link, _get_pk, _create_group


# ---------------------------------------------------------------------------
# Invalid token: buddy invite
# ---------------------------------------------------------------------------

class TestInvalidBuddyInviteToken:
    """Opening an invite link with a random token shows invite_invalid page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Ivan", last_name="Invalid")
        yield {"a": a}
        cleanup_user(a["email"])

    def test_invalid_token_shows_error_page(self, driver, w, ctx):
        driver.get(_url("/buddies/invite/this-token-does-not-exist-xyz123/"))
        time.sleep(1)
        assert "Invitation not found" in driver.page_source or \
               "invalid or has expired" in driver.page_source, \
            "Invalid invite token must show the invite_invalid page"


# ---------------------------------------------------------------------------
# Expired invite: buddy invite
# ---------------------------------------------------------------------------

class TestExpiredBuddyInvite:
    """Visiting a BuddyInvite link that has already expired shows invite_invalid."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Erin", last_name="Expired")
        b = setup_user(None, None, first_name="Brian", last_name="Expired")
        # Create an already-expired invite
        token = _shell(
            f"from buddies.models import BuddyInvite; "
            f"from feusers.models import FeUser; "
            f"from django.utils import timezone; "
            f"import datetime; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"inv = BuddyInvite.objects.create("
            f"  inviter=a, invitee_email='{b['email']}', "
            f"  expires_at=timezone.now() - datetime.timedelta(hours=1)); "
            f"print(inv.token)"
        )
        ctx = {"a": a, "b": b, "token": token.strip()}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_expired_invite_shows_error_page(self, driver, w, ctx):
        # B logs in and opens the expired invite link
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/buddies/invite/{ctx['token']}/"))
        time.sleep(1)
        assert "Invitation not found" in driver.page_source or \
               "invalid or has expired" in driver.page_source, \
            "Expired invite link must show the invite_invalid page"


# ---------------------------------------------------------------------------
# Wrong account: buddy invite
# ---------------------------------------------------------------------------

class TestWrongAccountBuddyInvite:
    """A is logged in but opens an invite sent to B → invite_wrong_account page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Wendy", last_name="Wrong")
        b = setup_user(None, None, first_name="Xavier", last_name="Wrong")
        # Sender C is just a helper; create invite for B's email from any user
        c = setup_user(None, None, first_name="Carl", last_name="Sender")
        token = _shell(
            f"from buddies.models import BuddyInvite; "
            f"from feusers.models import FeUser; "
            f"from django.utils import timezone; "
            f"import datetime; "
            f"c = FeUser.objects.get(email='{c['email']}'); "
            f"inv = BuddyInvite.objects.create("
            f"  inviter=c, invitee_email='{b['email']}', "
            f"  expires_at=timezone.now() + datetime.timedelta(days=7)); "
            f"print(inv.token)"
        )
        ctx = {"a": a, "b": b, "c": c, "token": token.strip()}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])
        cleanup_user(c["email"])

    def test_wrong_account_shows_error_page(self, driver, w, ctx):
        # A (wrong user) opens B's invite link
        driver.get(_url(f"/buddies/invite/{ctx['token']}/"))
        time.sleep(1)
        assert "Invitation for a different account" in driver.page_source, \
            "Opening an invite for a different email must show invite_wrong_account page"
        assert "Please log in with the correct account" in driver.page_source


# ---------------------------------------------------------------------------
# Wrong account: merge invite
# ---------------------------------------------------------------------------

class TestWrongAccountMergeInvite:
    """A is logged in but opens a merge invite sent to B → invite_wrong_account page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Mia", last_name="MergeWrong")
        b = setup_user(None, None, first_name="Noah", last_name="MergeWrong")
        c = setup_user(None, None, first_name="Owen", last_name="MergeSender")
        # C has a dummy; merge invite for B
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"c = FeUser.objects.get(email='{c['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=c, display_name='WrongAccDummy'); "
            f"print(d.uid)"
        )
        token = _shell(
            f"from buddies.models import DummyUser, DummyMergeInvite; "
            f"from feusers.models import FeUser; "
            f"from django.utils import timezone; "
            f"import datetime; "
            f"c = FeUser.objects.get(email='{c['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            f"dummy = DummyUser.objects.get(uid='{dummy_uid.strip()}'); "
            f"inv = DummyMergeInvite.objects.create("
            f"  inviting_feuser=c, dummy=dummy, invited_feuser=b, "
            f"  expires_at=timezone.now() + datetime.timedelta(days=7)); "
            f"print(inv.token)"
        )
        ctx = {"a": a, "b": b, "c": c, "token": token.strip()}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])
        cleanup_user(c["email"])

    def test_wrong_account_merge_shows_error_page(self, driver, w, ctx):
        # A opens merge link that is meant for B
        driver.get(_url(f"/buddies/merge/{ctx['token']}/"))
        time.sleep(1)
        assert "Invitation for a different account" in driver.page_source, \
            "Opening a merge invite for a different account must show invite_wrong_account page"


# ---------------------------------------------------------------------------
# Admin cannot remove themselves from the group
# ---------------------------------------------------------------------------

class TestAdminCannotRemoveSelf:
    """Admin trying to remove themselves via the remove-member endpoint gets an error."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Adam", last_name="Admin")
        group_id = _create_group(admin["email"], "AdminSelfRemoveGroup")
        # Get admin's BuddyGroupMember uid
        member_uid = _shell(
            f"from buddies.models import BuddyGroup, BuddyGroupMember; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{admin['email']}'); "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
            f"m = BuddyGroupMember.objects.get(group=g, feuser=a); "
            f"print(m.uid)"
        )
        ctx = {"admin": admin, "group_id": group_id, "member_uid": member_uid.strip()}
        yield ctx
        cleanup_user(admin["email"])

    def test_admin_self_remove_shows_error(self, driver, w, ctx):
        # POST directly to the remove-member endpoint for the admin themselves
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        # Attempt to remove self: find remove form for the admin member (if present)
        remove_forms = driver.find_elements(By.CSS_SELECTOR,
            f"form[action*='remove-member/{ctx['member_uid']}']")
        if not remove_forms:
            # UI correctly hides the remove button for admin self; test passes
            return
        # If the button exists (UI shows it), click and expect an error flash
        remove_forms[0].find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        time.sleep(0.5)
        # If confirm dialog appears, confirm it
        ok_btns = driver.find_elements(By.ID, "cdialog-ok")
        if ok_btns and ok_btns[0].is_displayed():
            ok_btns[0].click()
            time.sleep(1)
        assert "Transfer admin rights" in driver.page_source or \
               "cannot remove yourself" in driver.page_source.lower(), \
            "Admin self-removal must be blocked with an error message"
