"""
Achim Archive: personal (non-group) scenarios.

5.11a: Removing a dummy with expenses creates a personal Achim Archive
       and shows the "Achim appeared" modal.
5.11c: Bulk-deleting Achim Archive's expenses via the wipe confirmation page
       removes the archive and restores the clean buddy list.
5.11e: Popup does not appear again when Achim is re-created after the user
       has already seen it (has_seen_achim_intro flag).
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell


# ---------------------------------------------------------------------------
# Achim Archive created when dummy with expenses is removed
# ---------------------------------------------------------------------------

class TestAchimPersonalCreated:
    """Kick a dummy that has a shared expense: Achim Archive must appear."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Alex", last_name="Archiver")
        email = c["email"]
        dummy_id = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Vanishing Vera'); "
            f"print(d.pk)"
        )
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"create_expense(owning_feuser=u, title='Shared Dinner', "
            f"  type=TransactionType.EXPENSE, value=Decimal('80.00'), "
            f"  date_due=None, settled=False, "
            f"  buddy_spendings=[{{'type': 'dummy', 'id': {dummy_id}, 'share_percent': 50}}])"
        )
        c["dummy_id"] = int(dummy_id)
        yield c
        cleanup_user(c["email"])

    def test_dummy_visible_before_kick(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Vanishing Vera" in driver.page_source

    def test_kick_link_leads_to_confirm_page(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "a[href*='kick']").click()
        time.sleep(1)
        assert "kick" in driver.current_url

    def test_confirm_page_shows_expense_count(self, driver, w, ctx):
        assert "1" in driver.page_source
        assert "expense" in driver.page_source.lower()

    def test_confirm_page_shows_outstanding_balance(self, driver, w, ctx):
        assert "40.00" in driver.page_source, \
            "Confirm page must show 50% of 80.00 = 40.00 as outstanding balance"

    def test_confirm_page_mentions_achim(self, driver, w, ctx):
        assert "Achim Archive" in driver.page_source

    def test_submit_redirects_to_buddies_page(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-confirm-kick").click()
        time.sleep(1.5)
        assert "/buddies/" in driver.current_url

    def test_achim_modal_is_visible(self, driver, w, ctx):
        assert "Say hello to Achim Archive" in driver.page_source, \
            "Achim appearance modal must be shown after first archive creation"

    def test_vanishing_vera_gone(self, driver, w, ctx):
        assert "Vanishing Vera" not in driver.page_source

    def test_achim_archive_in_balance_list(self, driver, w, ctx):
        assert "Achim Archive" in driver.page_source, \
            "Achim Archive must appear in the buddy balance list"

    def test_achim_archive_pill_shown(self, driver, w, ctx):
        assert "Archive" in driver.page_source

    def test_archive_exists_in_db(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"print(DummyUser.objects.filter(owning_feuser=u, is_archive=True).count())"
        )
        assert count == "1", "Exactly one personal Achim Archive must exist in the DB"

    def test_original_expense_transferred_to_archive(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"archive = DummyUser.objects.get(owning_feuser=u, is_archive=True); "
            f"print(BuddySpending.objects.filter(participant_dummy=archive).count())"
        )
        assert count == "1", "Vera's BuddySpending row must now belong to Achim Archive"


# ---------------------------------------------------------------------------
# Wipe Achim Archive expenses via the warning confirmation page
# ---------------------------------------------------------------------------

class TestAchimPersonalWipe:
    """Wipe personal Achim Archive expenses: big warning page, then archive gone."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Willa", last_name="Wiper")
        email = c["email"]
        # Create an Achim Archive with one expense via shell
        _shell(
            f"from buddies.models import DummyUser; "
            f"from buddies.services.archive import BuddyArchiveService; "
            f"from feusers.models import FeUser; "
            f"from budget.models import Expense; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='TempBuddy'); "
            f"e = Expense.objects.create(owning_feuser=u, title='Wipe Test Expense', "
            f"  type='expense', value=Decimal('60.00'), settled=False, buddy_approved=True); "
            f"from buddies.models import BuddySpending; "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, "
            f"  share_percent=Decimal('50')); "
            f"archive, _ = BuddyArchiveService.get_or_create_personal_archive(u); "
            f"BuddyArchiveService.merge_dummy_into_dummy(d, archive); "
            f"d.delete(); "
            f"print('ok')"
        )
        yield c
        cleanup_user(c["email"])

    def test_achim_visible_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Achim Archive" in driver.page_source

    def test_delete_expenses_link_leads_to_wipe_page(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "a[href*='archive-wipe']").click()
        time.sleep(1)
        assert "archive-wipe" in driver.current_url

    def test_wipe_page_shows_expense_count(self, driver, w, ctx):
        assert "1 expense" in driver.page_source

    def test_wipe_page_shows_financial_impact(self, driver, w, ctx):
        assert "30.00" in driver.page_source, \
            "Wipe page must show feuser's share (50% of 60.00 = 30.00)"

    def test_wipe_page_has_warning(self, driver, w, ctx):
        assert "permanently" in driver.page_source.lower() or \
               "Warning" in driver.page_source

    def test_submit_wipes_and_redirects(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-confirm-wipe").click()
        time.sleep(1.5)
        assert "/buddies/" in driver.current_url

    def test_flash_message_shown(self, driver, w, ctx):
        assert "cleared" in driver.page_source.lower() or \
               "Achim Archive" in driver.page_source

    def test_achim_gone_from_balance_list(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Achim Archive" not in driver.page_source, \
            "Achim Archive must be gone after wipe"

    def test_archive_deleted_from_db(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"print(DummyUser.objects.filter(owning_feuser=u, is_archive=True).count())"
        )
        assert count == "0", "Achim Archive DummyUser must be deleted after wipe"


# ---------------------------------------------------------------------------
# Popup must not reappear when Achim is re-created (has_seen_achim_intro flag)
# ---------------------------------------------------------------------------

class TestAchimPersonalNoRepeatPopup:
    """Remove a dummy for a user who already has has_seen_achim_intro=True.
    The modal must NOT appear even though a new Achim Archive is created."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Rex", last_name="Repeat")
        email = c["email"]
        # Mark the user as having already seen the intro
        _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"u.has_seen_achim_intro = True; "
            f"u.save(update_fields=['has_seen_achim_intro'])"
        )
        dummy_id = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Repeat Randy'); "
            f"print(d.pk)"
        )
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"create_expense(owning_feuser=u, title='Repeat Dinner', "
            f"  type=TransactionType.EXPENSE, value=Decimal('50.00'), "
            f"  date_due=None, settled=False, "
            f"  buddy_spendings=[{{'type': 'dummy', 'id': {dummy_id}, 'share_percent': 50}}])"
        )
        c["dummy_id"] = int(dummy_id)
        yield c
        cleanup_user(c["email"])

    def test_kick_confirm_page_loads(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "a[href*='kick']").click()
        time.sleep(1)
        assert "kick" in driver.current_url

    def test_submit_redirects_to_buddies_page(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-confirm-kick").click()
        time.sleep(1.5)
        assert "/buddies/" in driver.current_url

    def test_achim_modal_not_shown(self, driver, w, ctx):
        assert "Say hello to Achim Archive" not in driver.page_source, \
            "Achim popup must not appear for a user who has already seen it"

    def test_achim_archive_still_created(self, driver, w, ctx):
        assert "Achim Archive" in driver.page_source, \
            "Achim Archive must still appear in the buddy list even without the popup"
