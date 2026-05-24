"""
Partnership onboarding wizard: stoerer banner, decline, and full happy path.
All DB state is set up via shell; UI tests only verify rendering.
Run with: pytest tests/e2e/buddies/test_partnership_onboarding.py -v -s
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_buddy_link


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


def _add_tag(email: str, title: str) -> None:
    _shell(
        "from feusers.models import FeUser; from budget.models import Tag; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"Tag.objects.get_or_create(owning_feuser=u, title='{title}')"
    )


def _add_category(email: str, title: str) -> None:
    _shell(
        "from feusers.models import FeUser; from budget.models import Category; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"Category.objects.get_or_create(owning_feuser=u, title='{title}')"
    )


def _onboarding_complete(email: str) -> str:
    return _shell(
        "from feusers.models import FeUser; "
        "from buddies.models import CatalogPartnershipMembership; "
        f"u = FeUser.objects.get(email='{email}'); "
        "m = CatalogPartnershipMembership.objects.get(feuser=u); "
        "print(m.onboarding_complete)"
    )


# ---------------------------------------------------------------------------
# Stoerer banner for pending invite
# ---------------------------------------------------------------------------

class TestStoererBannerVisible:
    """A user with a pending invite sees the stoerer banner on all pages."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(None, None, first_name="Amy", last_name="Stoer")
        b = setup_user(driver, w, first_name="Bill", last_name="Stoer")
        _create_buddy_link(a["email"], b["email"])
        token = _create_invite_via_shell(a["email"], b["email"])
        yield {"a": a, "b": b, "token": token}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_stoerer_contains_wizard_link(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert ctx["token"] in driver.page_source

    def test_stoerer_visible_on_expenses_page(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        time.sleep(1)
        assert ctx["token"] in driver.page_source


# ---------------------------------------------------------------------------
# Decline invite
# ---------------------------------------------------------------------------

class TestDeclinePartnership:
    """B clicks 'I don't want a partnership' in step 1 of the wizard."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(None, None, first_name="Ann", last_name="Decl")
        b = setup_user(driver, w, first_name="Bob", last_name="Decl")
        _create_buddy_link(a["email"], b["email"])
        token = _create_invite_via_shell(a["email"], b["email"])
        yield {"a": a, "b": b, "token": token}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_wizard_page_renders(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/buddies/partnership/accept/{ctx['token']}/"))
        time.sleep(1.5)
        assert driver.find_element(By.ID, "step1-decline").is_displayed()

    def test_decline_redirects_away(self, driver, w, ctx):
        driver.find_element(By.ID, "step1-decline").click()
        time.sleep(0.8)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert "/buddies/partnership/accept/" not in driver.current_url

    def test_invite_marked_declined_in_db(self, driver, w, ctx):
        # The invite is either marked accepted=False or cascade-deleted when the
        # solo partnership dissolves after decline — either way no pending invite remains.
        count = _shell(
            "from buddies.models import CatalogPartnershipInvite; "
            f"print(CatalogPartnershipInvite.objects.filter(token='{ctx['token']}', status__in=['pending','in_setup']).count())"
        )
        assert count == "0", "Pending invite should no longer exist after decline"

    def test_no_membership_created(self, driver, w, ctx):
        count = _shell(
            "from feusers.models import FeUser; "
            "from buddies.models import CatalogPartnershipMembership; "
            f"u = FeUser.objects.get(email='{ctx['b']['email']}'); "
            "print(CatalogPartnershipMembership.objects.filter(feuser=u).count())"
        )
        assert count == "0"


# ---------------------------------------------------------------------------
# Full wizard happy path (no unmatched tags/cats → steps are trivially valid)
# ---------------------------------------------------------------------------

class TestOnboardingHappyPathNoConflicts:
    """When catalogs are identical, all 4 steps can be completed without mapping."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(None, None, first_name="Cara", last_name="Happy")
        b = setup_user(driver, w, first_name="Dan", last_name="Happy")
        _create_buddy_link(a["email"], b["email"])
        # Give A a catalog; B has nothing → nothing to map
        _add_tag(a["email"], "groceries")
        _add_category(a["email"], "Food")
        token = _create_invite_via_shell(a["email"], b["email"])
        yield {"a": a, "b": b, "token": token}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_step1_next(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/buddies/partnership/accept/{ctx['token']}/"))
        time.sleep(1.5)
        driver.find_element(By.ID, "step1-next").click()
        time.sleep(0.8)
        assert driver.find_element(By.ID, "step-2").is_displayed()

    def test_step2_next(self, driver, w, ctx):
        # No unmatched tags → step is already valid
        driver.find_element(By.ID, "step2-next").click()
        time.sleep(0.8)
        assert driver.find_element(By.ID, "step-3").is_displayed()

    def test_step3_next(self, driver, w, ctx):
        driver.find_element(By.ID, "step3-next").click()
        time.sleep(0.8)
        assert driver.find_element(By.ID, "step-4").is_displayed()

    def test_apply_redirects_to_cats_page(self, driver, w, ctx):
        driver.find_element(By.ID, "step4-apply").click()
        time.sleep(3)
        assert "/budget/categories" in driver.current_url

    def test_membership_marked_complete(self, driver, w, ctx):
        assert _onboarding_complete(ctx["b"]["email"]) == "True"

    def test_b_catalog_copied_from_a(self, driver, w, ctx):
        b_tags = _shell(
            "from feusers.models import FeUser; from budget.models import Tag; "
            f"u = FeUser.objects.get(email='{ctx['b']['email']}'); "
            "print(','.join(sorted(Tag.objects.filter(owning_feuser=u).values_list('title', flat=True))))"
        )
        assert "groceries" in b_tags


# ---------------------------------------------------------------------------
# Wizard with unmatched tags: DROP them to proceed
# ---------------------------------------------------------------------------

class TestOnboardingWithUnmatchedTags:
    """B has tags not in A's catalog; the wizard shows mapping rows; DROP clears validation."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(None, None, first_name="Ella", last_name="Map")
        b = setup_user(driver, w, first_name="Fred", last_name="Map")
        _create_buddy_link(a["email"], b["email"])
        _add_tag(a["email"], "transport")
        # B has a tag NOT in A's catalog
        _add_tag(b["email"], "uniquetag_xyz")
        token = _create_invite_via_shell(a["email"], b["email"])
        yield {"a": a, "b": b, "token": token}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_step2_shows_mapping_row(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/buddies/partnership/accept/{ctx['token']}/"))
        time.sleep(1.5)
        driver.find_element(By.ID, "step1-next").click()
        time.sleep(0.8)
        rows = driver.find_elements(By.CSS_SELECTOR, "#step-2 .wizard-map-row")
        assert rows, "Expected at least one mapping row for unmatched tag"

    def test_step2_blocked_without_decision(self, driver, w, ctx):
        # Clicking Next without deciding should not advance
        driver.find_element(By.ID, "step2-next").click()
        time.sleep(0.5)
        assert driver.find_element(By.ID, "step-2").is_displayed(), \
            "Step 2 should remain active when undecided rows exist"

    def test_step2_drop_unblocks_next(self, driver, w, ctx):
        # Check DROP on all rows
        rows = driver.find_elements(By.CSS_SELECTOR, "#step-2 .wizard-map-row")
        for row in rows:
            cb = row.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
            if not cb.is_selected():
                cb.click()
                time.sleep(0.3)
        driver.find_element(By.ID, "step2-next").click()
        time.sleep(0.8)
        assert driver.find_element(By.ID, "step-3").is_displayed()
