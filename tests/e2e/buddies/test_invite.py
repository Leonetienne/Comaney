"""
Real buddy invitation flows: send, accept via email link, decline, revoke.
Each class is fully isolated (own user pair, own cleanup).
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, setup_user, cleanup_user,
    fetch_email, extract_link, mailpit_seen_ids,
)
from bhelpers import _shell, _login_as


# ---------------------------------------------------------------------------
# Send invite and accept via email link
# ---------------------------------------------------------------------------

class TestBuddyInviteAccept:
    """A sends invite; B accepts via the link from the email."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Alice", last_name="Inviter")
        b = setup_user(None, None, first_name="Bob", last_name="Invitee")
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_sends_invite(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite-actual'] input[name='email']")
        inp.clear()
        inp.send_keys(ctx["b"]["email"])
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite-actual'] button[type=submit]").click()
        time.sleep(1)
        assert "Buddy invitations you sent" in driver.page_source
        assert ctx["b"]["email"] in driver.page_source

    def test_invite_email_arrives(self, driver, w, ctx):
        body = fetch_email(ctx["b"]["email"], "invited you to be spending buddies")
        ctx["invite_link"] = extract_link(body)
        assert "/buddies/invite/" in ctx["invite_link"]

    def test_b_sees_pending_invite_on_buddies_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Buddy invitations" in driver.page_source
        assert ctx["a"]["email"] in driver.page_source

    def test_b_accepts_via_invite_link(self, driver, w, ctx):
        driver.get(ctx["invite_link"])
        time.sleep(1)
        assert "invited you to be spending buddies" in driver.page_source
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='accept'] button[type=submit]").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_b_sees_a_as_buddy_after_accept(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert ctx["a"]["email"] in driver.page_source

    def test_a_sees_b_as_buddy_after_accept(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert ctx["b"]["email"] in driver.page_source


# ---------------------------------------------------------------------------
# Decline invite
# ---------------------------------------------------------------------------

class TestBuddyInviteDecline:
    """A sends invite; B declines directly from the buddies page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Anna", last_name="Decliner")
        b = setup_user(None, None, first_name="Ben", last_name="Decliner")
        # A sends the invite via shell to avoid email-checking overhead
        a_pk = _shell(f"from feusers.models import FeUser; print(FeUser.objects.get(email='{a['email']}').pk)")
        b_email = b["email"]
        _shell(
            f"from buddies.models import BuddyInvite; "
            f"from feusers.models import FeUser; "
            f"inviter = FeUser.objects.get(pk={a_pk}); "
            f"inv = BuddyInvite(inviter=inviter, invitee_email='{b_email}'); "
            f"inv.save()"
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_b_sees_incoming_invite(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Buddy invitations" in driver.page_source

    def test_b_declines_invite(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR,
            ".invite-card form[action*='decline'] button[type=submit]").click()
        time.sleep(1)
        assert "Buddy invitations" not in driver.page_source
        assert ctx["a"]["email"] not in driver.page_source

    def test_no_buddy_link_after_decline(self, driver, w, ctx):
        link_count = _shell(
            f"from buddies.models import BuddyLink; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"from django.db.models import Q; "
            f"print(BuddyLink.objects.filter(Q(user_a=a)|Q(user_b=a)).filter(Q(user_a=b)|Q(user_b=b)).count())"
        )
        assert link_count == "0"


# ---------------------------------------------------------------------------
# Revoke invite (sender withdraws)
# ---------------------------------------------------------------------------

class TestBuddyInviteRevoke:
    """A sends invite; A revokes it before B responds."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Rex", last_name="Revoker")
        b = setup_user(None, None, first_name="Bianca", last_name="Revoker")
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_sends_invite(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite-actual'] input[name='email']")
        inp.clear()
        inp.send_keys(ctx["b"]["email"])
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite-actual'] button[type=submit]").click()
        time.sleep(1)
        assert ctx["b"]["email"] in driver.page_source

    def test_a_revokes_invite(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR,
            ".invite-card-outgoing form[action*='revoke'] button[type=submit]").click()
        time.sleep(1)
        assert "Buddy invitations you sent" not in driver.page_source
        assert ctx["b"]["email"] not in driver.page_source

    def test_b_sees_no_invite_after_revoke(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Buddy invitations" not in driver.page_source
