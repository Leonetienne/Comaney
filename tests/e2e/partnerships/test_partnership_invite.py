"""
Partnership invite flow: button visibility, badge, and pill states.
Each class is fully independent; DB state is always set up via shell.
Run with: pytest tests/e2e/buddies/test_partnership_invite.py -v -s
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_buddy_link, _get_pk


def _create_invite_via_shell(inviter_email: str, invitee_email: str) -> str:
    """Create partnership + pending invite; return token."""
    return _shell(
        "from feusers.models import FeUser; "
        "from buddies.models import CatalogPartnership, CatalogPartnershipMembership, CatalogPartnershipInvite; "
        f"inviter = FeUser.objects.get(email='{inviter_email}'); "
        f"invitee = FeUser.objects.get(email='{invitee_email}'); "
        "p = CatalogPartnership.objects.create(); "
        "CatalogPartnershipMembership.objects.create(partnership=p, feuser=inviter, onboarding_complete=True); "
        "inv = CatalogPartnershipInvite.objects.create(partnership=p, inviter=inviter, invitee_email=invitee.email); "
        "print(inv.token)"
    )


def _create_full_partnership_via_shell(email_a: str, email_b: str) -> None:
    """Wire both users into a completed partnership."""
    _shell(
        "from feusers.models import FeUser; "
        "from buddies.models import CatalogPartnership, CatalogPartnershipMembership, CatalogPartnershipInvite; "
        f"a = FeUser.objects.get(email='{email_a}'); "
        f"b = FeUser.objects.get(email='{email_b}'); "
        "p = CatalogPartnership.objects.create(); "
        "CatalogPartnershipMembership.objects.create(partnership=p, feuser=a, onboarding_complete=True); "
        "CatalogPartnershipMembership.objects.create(partnership=p, feuser=b, onboarding_complete=True); "
        "CatalogPartnershipInvite.objects.create(partnership=p, inviter=a, invitee_email=b.email, status='active')"
    )


# ---------------------------------------------------------------------------
# Invite button visible for connected user
# ---------------------------------------------------------------------------

class TestInviteButtonVisible:
    """A buddy list shows 'Invite as partner' when users share a BuddyLink."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Alice", last_name="Btn")
        b = setup_user(None, None, first_name="Bob", last_name="Btn")
        _create_buddy_link(a["email"], b["email"])
        b_pk = _get_pk(b["email"])
        yield {"a": a, "b": b, "b_pk": b_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_invite_button_visible_on_buddies(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        btn = driver.find_elements(
            By.CSS_SELECTOR,
            f"button.partnership-invite-btn[data-feuser-id='{ctx['b_pk']}']",
        )
        assert btn, "Expected 'Invite as partner' button for B"


# ---------------------------------------------------------------------------
# Send invite via UI button (single focused test)
# ---------------------------------------------------------------------------

class TestInviteSendViaButton:
    """Clicking 'Invite as partner' and confirming creates an invite in DB."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Carl", last_name="Send")
        b = setup_user(None, None, first_name="Dana", last_name="Send")
        _create_buddy_link(a["email"], b["email"])
        b_pk = _get_pk(b["email"])
        yield {"a": a, "b": b, "b_pk": b_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_send_invite_and_pill_appears(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)

        btn = driver.find_element(
            By.CSS_SELECTOR,
            f"button.partnership-invite-btn[data-feuser-id='{ctx['b_pk']}']",
        )
        btn.click()
        time.sleep(1)

        # Confirm the cdialog
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)

        # Invite should be in DB
        count = _shell(
            "from buddies.models import CatalogPartnershipInvite; "
            f"print(CatalogPartnershipInvite.objects.filter(invitee_email='{ctx['b']['email']}', status__in=['pending','in_setup']).count())"
        )
        assert count == "1", f"Expected invite in DB, got count={count}"

        # UI should show pill (may need page reload since outerHTML swap is client-side)
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Invite pending" in driver.page_source


# ---------------------------------------------------------------------------
# Badge visible for invitee
# ---------------------------------------------------------------------------

class TestBadgeVisibleForInvitee:
    """When a pending invite exists, invitee sees an action badge."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(None, None, first_name="Eve", last_name="Badge")
        b = setup_user(driver, w, first_name="Frank", last_name="Badge")
        _create_buddy_link(a["email"], b["email"])
        token = _create_invite_via_shell(a["email"], b["email"])
        yield {"a": a, "b": b, "token": token}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_sidebar_badge_count(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        badges = driver.find_elements(By.CSS_SELECTOR, ".action-badge")
        assert badges, "Expected at least one action badge for pending invite"

    def test_badge_links_to_categories_page(self, driver, w, ctx):
        # Badge is on the Categories & Tags nav item
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        # Pending invite card should show
        assert ctx["a"]["email"] in driver.page_source or "invited you" in driver.page_source


# ---------------------------------------------------------------------------
# Invite-pending pill shown on buddy list
# ---------------------------------------------------------------------------

class TestInvitePendingPill:
    """After invite is sent, inviter sees 'Invite pending' pill, not the button."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Grace", last_name="Pending")
        b = setup_user(None, None, first_name="Hank", last_name="Pending")
        _create_buddy_link(a["email"], b["email"])
        _create_invite_via_shell(a["email"], b["email"])
        b_pk = _get_pk(b["email"])
        yield {"a": a, "b": b, "b_pk": b_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_pending_pill_shown_not_button(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Invite pending" in driver.page_source
        btns = driver.find_elements(
            By.CSS_SELECTOR,
            f"button.partnership-invite-btn[data-feuser-id='{ctx['b_pk']}']",
        )
        assert not btns, "Invite button should be replaced by pill once invite is pending"


# ---------------------------------------------------------------------------
# Partner pill when already partners
# ---------------------------------------------------------------------------

class TestPartnerPill:
    """When fully partnered, buddy list shows green 'Partner' pill."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Iris", last_name="Partner")
        b = setup_user(None, None, first_name="Jack", last_name="Partner")
        _create_buddy_link(a["email"], b["email"])
        _create_full_partnership_via_shell(a["email"], b["email"])
        b_pk = _get_pk(b["email"])
        yield {"a": a, "b": b, "b_pk": b_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_partner_pill_shown(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Partner" in driver.page_source
        btns = driver.find_elements(
            By.CSS_SELECTOR,
            f"button.partnership-invite-btn[data-feuser-id='{ctx['b_pk']}']",
        )
        assert not btns, "Invite button should not appear when already partners"


# ---------------------------------------------------------------------------
# No invite button without mutual connection
# ---------------------------------------------------------------------------

class TestNoInviteButtonWithoutConnection:
    """Users with no buddy link / shared project never see the invite button."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Kim", last_name="NoLink")
        b = setup_user(None, None, first_name="Leo", last_name="NoLink")
        # Deliberately no buddy link
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_no_invite_button_on_buddies(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        # B isn't even in A's buddy list, so no button
        assert ctx["b"]["email"] not in driver.page_source
