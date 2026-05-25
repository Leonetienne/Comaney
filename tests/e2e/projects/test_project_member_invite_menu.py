"""
Project member list: non-admin members get a restricted "..." menu that lets
them invite a fellow member as a Catalog Partner or as a direct buddy, with
each option hidden once it no longer applies.
Run with: pytest tests/e2e/projects/test_project_member_invite_menu.py -v -s
"""
import subprocess
import time
import uuid

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, fill, click, DOCKER_WEB, PASSWORD
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _create_group, _add_group_member,
    _get_pk, _ctx_click,
)


def _create_full_partnership_via_shell(email_a: str, email_b: str) -> None:
    """Wire both users into a completed Catalog Partnership."""
    _shell(
        "from feusers.models import FeUser; "
        "from buddies.models import CatalogPartnership, CatalogPartnershipMembership; "
        f"a = FeUser.objects.get(email='{email_a}'); "
        f"b = FeUser.objects.get(email='{email_b}'); "
        "p = CatalogPartnership.objects.create(); "
        "CatalogPartnershipMembership.objects.create(partnership=p, feuser=a, onboarding_complete=True); "
        "CatalogPartnershipMembership.objects.create(partnership=p, feuser=b, onboarding_complete=True)"
    )


def _settings_url(gid) -> str:
    return _url(f"/projects/{gid}/settings/")


# ---------------------------------------------------------------------------
# Both options visible when no relation exists yet
# ---------------------------------------------------------------------------

class TestBothOptionsVisibleForNonAdmin:
    """A non-admin member sees the ... menu with both invite options."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Mona", last_name="Owner")
        member = setup_user(driver, w, first_name="Otto", last_name="Member")
        gid = _create_group(admin["email"], "Menu Test Project")
        _add_group_member(int(gid), member["email"])
        admin_pk = _get_pk(admin["email"])
        yield {"admin": admin, "member": member, "gid": int(gid), "admin_pk": admin_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_menu_has_both_invite_buttons(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        partner_btn = driver.find_elements(
            By.CSS_SELECTOR, f"button.partnership-invite-btn[data-feuser-id='{ctx['admin_pk']}']")
        buddy_btn = driver.find_elements(
            By.CSS_SELECTOR, f"button.buddy-invite-btn[data-feuser-id='{ctx['admin_pk']}']")
        assert partner_btn, "Expected 'Invite as partner' for the admin row"
        assert buddy_btn, "Expected 'Invite as direct buddy' for the admin row"

    def test_admin_kebab_menu_unaffected(self, driver, w, ctx):
        """Regression guard: the admin's own kebab menu keeps its existing items only."""
        _login_as(driver, ctx["admin"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        buddy_btn = driver.find_elements(By.CSS_SELECTOR, "button.buddy-invite-btn")
        assert not buddy_btn, "Admin's kebab menu should not gain the new buddy-invite button"


# ---------------------------------------------------------------------------
# Buddy option disappears once they are already buddies
# ---------------------------------------------------------------------------

class TestBuddyOptionHiddenWhenAlreadyBuddies:
    """Once linked as buddies, only 'Invite as partner' remains."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Pia", last_name="Owner")
        member = setup_user(driver, w, first_name="Quinn", last_name="Member")
        gid = _create_group(admin["email"], "Menu Buddy Project")
        _add_group_member(int(gid), member["email"])
        _create_buddy_link(admin["email"], member["email"])
        admin_pk = _get_pk(admin["email"])
        yield {"admin": admin, "member": member, "gid": int(gid), "admin_pk": admin_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_buddy_button_gone_partner_button_present(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        buddy_btn = driver.find_elements(
            By.CSS_SELECTOR, f"button.buddy-invite-btn[data-feuser-id='{ctx['admin_pk']}']")
        partner_btn = driver.find_elements(
            By.CSS_SELECTOR, f"button.partnership-invite-btn[data-feuser-id='{ctx['admin_pk']}']")
        assert not buddy_btn, "Already buddies: 'Invite as direct buddy' must be hidden"
        assert partner_btn, "'Invite as partner' should still be available"


# ---------------------------------------------------------------------------
# Whole menu disappears once neither action applies anymore
# ---------------------------------------------------------------------------

class TestMenuHiddenWhenNothingApplies:
    """When buddies and partners already, the ... menu itself disappears."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Ravi", last_name="Owner")
        member = setup_user(driver, w, first_name="Sara", last_name="Member")
        gid = _create_group(admin["email"], "Menu None Project")
        _add_group_member(int(gid), member["email"])
        _create_buddy_link(admin["email"], member["email"])
        _create_full_partnership_via_shell(admin["email"], member["email"])
        yield {"admin": admin, "member": member, "gid": int(gid)}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_no_ctx_menu_for_fully_connected_member(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        assert "Partner" in driver.page_source
        assert not driver.find_elements(By.CSS_SELECTOR, ".ctx-menu-wrap"), (
            "Non-admin member list should show no ... menu once neither action applies"
        )


# ---------------------------------------------------------------------------
# Sending the invite via the UI button creates a BuddyInvite
# ---------------------------------------------------------------------------

class TestSendBuddyInviteViaMenu:
    """Clicking 'Invite as direct buddy' and confirming creates an invite."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Tara", last_name="Owner")
        member = setup_user(driver, w, first_name="Umar", last_name="Member")
        gid = _create_group(admin["email"], "Menu Send Project")
        _add_group_member(int(gid), member["email"])
        admin_pk = _get_pk(admin["email"])
        yield {"admin": admin, "member": member, "gid": int(gid), "admin_pk": admin_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_send_buddy_invite_and_pill_appears(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)

        _ctx_click(driver, f"button.buddy-invite-btn[data-feuser-id='{ctx['admin_pk']}']")
        time.sleep(1)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)

        count = _shell(
            "from buddies.models import BuddyInvite; "
            f"print(BuddyInvite.objects.filter(inviter__email='{ctx['member']['email']}', "
            f"invitee_email='{ctx['admin']['email']}').count())"
        )
        assert count == "1", f"Expected a BuddyInvite in DB, got count={count}"

        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        assert "Buddy invite pending" in driver.page_source
        buddy_btn = driver.find_elements(
            By.CSS_SELECTOR, f"button.buddy-invite-btn[data-feuser-id='{ctx['admin_pk']}']")
        assert not buddy_btn, "Button should be replaced by the pending pill"


# ---------------------------------------------------------------------------
# Demo viewers never see the menu, regardless of relation state
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


class TestDemoViewerNeverSeesMenu:
    """A demo project member never sees the ... menu, even with no relation."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        if not _demo_users_enabled():
            pytest.skip("ENABLE_DEMO_USERS is not set on this server")
        admin = setup_user(None, None, first_name="Vik", last_name="Owner")
        demo_member = _create_demo_member("Wren", "Demo")
        gid = _create_group(admin["email"], "Menu Demo Project")
        _add_group_member(int(gid), demo_member["email"])
        yield {"admin": admin, "member": demo_member, "gid": int(gid)}
        cleanup_user(admin["email"])
        cleanup_user(demo_member["email"])

    def test_no_ctx_menu_for_demo_viewer(self, driver, w, ctx):
        _demo_login_and_accept(driver, w, ctx["member"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        assert not driver.find_elements(By.CSS_SELECTOR, ".ctx-menu-wrap"), (
            "Demo viewers must never see the ... menu on the member list"
        )
