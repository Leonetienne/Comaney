"""
Partnership dissolution: leave and kick flows.
All partnerships are created via shell; each class is fully independent.
Run with: pytest tests/e2e/buddies/test_partnership_dissolution.py -v -s
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _get_pk


def _setup_two_member_partnership(email_a: str, email_b: str) -> None:
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


def _setup_three_member_partnership(email_a: str, email_b: str, email_c: str) -> None:
    _shell(
        "from feusers.models import FeUser; "
        "from buddies.models import CatalogPartnership, CatalogPartnershipMembership, CatalogPartnershipInvite; "
        f"a = FeUser.objects.get(email='{email_a}'); "
        f"b = FeUser.objects.get(email='{email_b}'); "
        f"c = FeUser.objects.get(email='{email_c}'); "
        "p = CatalogPartnership.objects.create(); "
        "CatalogPartnershipMembership.objects.create(partnership=p, feuser=a, onboarding_complete=True); "
        "CatalogPartnershipMembership.objects.create(partnership=p, feuser=b, onboarding_complete=True); "
        "CatalogPartnershipMembership.objects.create(partnership=p, feuser=c, onboarding_complete=True); "
        "CatalogPartnershipInvite.objects.create(partnership=p, inviter=a, invitee_email=b.email, status='active'); "
        "CatalogPartnershipInvite.objects.create(partnership=p, inviter=a, invitee_email=c.email, status='active')"
    )


def _membership_count(email: str) -> int:
    return int(_shell(
        "from feusers.models import FeUser; "
        "from buddies.models import CatalogPartnershipMembership; "
        f"u = FeUser.objects.get(email='{email}'); "
        "print(CatalogPartnershipMembership.objects.filter(feuser=u).count())"
    ))


# ---------------------------------------------------------------------------
# Leave partnership
# ---------------------------------------------------------------------------

class TestLeavePartnership:
    """B leaves the partnership; solo partnership dissolves (A removed too)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(None, None, first_name="Leo", last_name="Leave")
        b = setup_user(driver, w, first_name="Mia", last_name="Leave")
        _setup_two_member_partnership(a["email"], b["email"])
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_leave_button_visible(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        btn = driver.find_element(By.ID, "partnership-leave-btn")
        assert btn.is_displayed()

    def test_leave_removes_b_membership(self, driver, w, ctx):
        driver.find_element(By.ID, "partnership-leave-btn").click()
        time.sleep(0.8)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert _membership_count(ctx["b"]["email"]) == 0

    def test_solo_partnership_dissolves(self, driver, w, ctx):
        # A was the only remaining member → partnership dissolves
        assert _membership_count(ctx["a"]["email"]) == 0

    def test_leave_button_gone_after_reload(self, driver, w, ctx):
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        # Check DOM — the button ID also appears as a JS string literal in page_source
        btns = driver.find_elements(By.ID, "partnership-leave-btn")
        assert not btns, "Leave button should not be in DOM after membership is gone"


# ---------------------------------------------------------------------------
# Kick a partner
# ---------------------------------------------------------------------------

class TestKickPartner:
    """A kicks B; B's membership is removed; solo partnership dissolves."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Nick", last_name="Kick")
        b = setup_user(None, None, first_name="Olga", last_name="Kick")
        _setup_two_member_partnership(a["email"], b["email"])
        b_pk = _get_pk(b["email"])
        yield {"a": a, "b": b, "b_pk": b_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_kick_button_visible(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        btn = driver.find_element(
            By.CSS_SELECTOR, f"button.partner-kick-btn[data-feuser-id='{ctx['b_pk']}']"
        )
        assert btn.is_displayed()

    def test_kick_removes_b_membership(self, driver, w, ctx):
        driver.find_element(
            By.CSS_SELECTOR, f"button.partner-kick-btn[data-feuser-id='{ctx['b_pk']}']"
        ).click()
        time.sleep(0.8)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert _membership_count(ctx["b"]["email"]) == 0

    def test_solo_partnership_dissolves_after_kick(self, driver, w, ctx):
        assert _membership_count(ctx["a"]["email"]) == 0

    def test_kicked_partner_not_shown_after_reload(self, driver, w, ctx):
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        assert ctx["b"]["email"] not in driver.page_source


# ---------------------------------------------------------------------------
# Three-member group: one leaves, two remain
# ---------------------------------------------------------------------------

class TestThreeMemberLeave:
    """C leaves a 3-person group; A and B remain in the partnership."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(None, None, first_name="Paula", last_name="Trio")
        b = setup_user(None, None, first_name="Quinn", last_name="Trio")
        c = setup_user(driver, w, first_name="Rosa", last_name="Trio")
        _setup_three_member_partnership(a["email"], b["email"], c["email"])
        yield {"a": a, "b": b, "c": c}
        cleanup_user(a["email"])
        cleanup_user(b["email"])
        cleanup_user(c["email"])

    def test_c_leaves(self, driver, w, ctx):
        _login_as(driver, ctx["c"])
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        driver.find_element(By.ID, "partnership-leave-btn").click()
        time.sleep(0.8)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert _membership_count(ctx["c"]["email"]) == 0

    def test_a_still_in_partnership(self, driver, w, ctx):
        assert _membership_count(ctx["a"]["email"]) == 1

    def test_b_still_in_partnership(self, driver, w, ctx):
        assert _membership_count(ctx["b"]["email"]) == 1
