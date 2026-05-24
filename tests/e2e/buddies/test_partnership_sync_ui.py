"""
Catalog sync after a completed partnership:
  - Tag/category created by A appears in B's catalog (DB check)
  - B sees the new item on the categories page (UI check)
  - Deletion dialog warns about partnership impact
  - Non-complete members do NOT receive sync
Run with: pytest tests/e2e/buddies/test_partnership_sync_ui.py -v -s
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as


def _setup_full_partnership(email_a: str, email_b: str) -> None:
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


def _count_tags(email: str, title: str) -> int:
    return int(_shell(
        "from feusers.models import FeUser; from budget.models import Tag; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"print(Tag.objects.filter(owning_feuser=u, title='{title}').count())"
    ))


def _count_categories(email: str, title: str) -> int:
    return int(_shell(
        "from feusers.models import FeUser; from budget.models import Category; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"print(Category.objects.filter(owning_feuser=u, title='{title}').count())"
    ))


def _enter_in_input(driver, element_id: str, value: str) -> None:
    """Set value on a plain-text input and dispatch Enter keydown to trigger creation."""
    inp = driver.find_element(By.ID, element_id)
    driver.execute_script("arguments[0].value = arguments[1];", inp, value)
    driver.execute_script(
        "arguments[0].dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));",
        inp,
    )


# ---------------------------------------------------------------------------
# Tag sync: A creates tag → B gets it
# ---------------------------------------------------------------------------

class TestTagSyncCreate:
    """A creates a tag via the UI; B's catalog gets it automatically."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Amy", last_name="TagSync")
        b = setup_user(None, None, first_name="Ben", last_name="TagSync")
        _setup_full_partnership(a["email"], b["email"])
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_creates_tag(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        _enter_in_input(driver, "tag-input", "vacation")
        time.sleep(1.5)
        assert "vacation" in driver.page_source

    def test_b_has_tag_in_db(self, driver, w, ctx):
        assert _count_tags(ctx["b"]["email"], "vacation") == 1

    def test_b_sees_tag_in_ui(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        assert "vacation" in driver.page_source


# ---------------------------------------------------------------------------
# Category sync: A creates category → B gets it
# ---------------------------------------------------------------------------

class TestCategorySyncCreate:
    """A creates a category via the UI; B's catalog gets it automatically."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Carl", last_name="CatSync")
        b = setup_user(None, None, first_name="Dana", last_name="CatSync")
        _setup_full_partnership(a["email"], b["email"])
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_creates_category(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        _enter_in_input(driver, "category-input", "Utilities")
        time.sleep(1.5)
        assert "Utilities" in driver.page_source

    def test_b_has_category_in_db(self, driver, w, ctx):
        assert _count_categories(ctx["b"]["email"], "Utilities") == 1

    def test_b_sees_category_in_ui(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        assert "Utilities" in driver.page_source


# ---------------------------------------------------------------------------
# Deletion warning dialog
# ---------------------------------------------------------------------------

class TestDeletionWarningDialog:
    """Deleting a tag while in a partnership shows a warning in the confirm dialog."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Eve", last_name="DelWarn")
        b = setup_user(None, None, first_name="Frank", last_name="DelWarn")
        _setup_full_partnership(a["email"], b["email"])
        _shell(
            "from feusers.models import FeUser; from budget.models import Tag; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            "Tag.objects.get_or_create(owning_feuser=u, title='warntag')"
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_delete_dialog_mentions_partners(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        assert "warntag" in driver.page_source
        # Click the delete button for 'warntag'
        btn = driver.find_element(By.CSS_SELECTOR, "button.ct-delete[data-title='warntag']")
        btn.click()
        time.sleep(0.8)
        dialog = driver.find_element(By.CSS_SELECTOR, ".cdialog")
        assert "partner" in dialog.text.lower()


# ---------------------------------------------------------------------------
# Non-onboarded partner does NOT receive sync
# ---------------------------------------------------------------------------

class TestNoSyncBeforeOnboarding:
    """Sync is skipped for partners with onboarding_complete=False."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Greg", last_name="NoSync")
        b = setup_user(None, None, first_name="Hanna", last_name="NoSync")
        _shell(
            "from feusers.models import FeUser; "
            "from buddies.models import CatalogPartnership, CatalogPartnershipMembership, CatalogPartnershipInvite; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            "p = CatalogPartnership.objects.create(); "
            "CatalogPartnershipMembership.objects.create(partnership=p, feuser=a, onboarding_complete=True); "
            "CatalogPartnershipMembership.objects.create(partnership=p, feuser=b, onboarding_complete=False); "
            "CatalogPartnershipInvite.objects.create(partnership=p, inviter=a, invitee_email=b.email, status='pending')"
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_tag_does_not_reach_incomplete_partner(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        _enter_in_input(driver, "tag-input", "shouldnotreach")
        time.sleep(1.5)
        assert _count_tags(ctx["b"]["email"], "shouldnotreach") == 0
