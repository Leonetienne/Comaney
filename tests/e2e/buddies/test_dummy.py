"""
Personal dummy buddy: add, kick (no debt / with debt), onboarding hint,
is_dummy expense visibility (hidden from API, visible on buddies summary).
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, api_get
from bhelpers import _shell, _confirm


# ---------------------------------------------------------------------------
# Onboarding hint + add dummy + kick without debt
# ---------------------------------------------------------------------------

class TestDummyCRUD:
    """Add a dummy, verify it appears, kick without debt."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Diana", last_name="Dummy")
        yield c
        cleanup_user(c["email"])

    def test_onboarding_hint_no_buddies(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "How Buddies work:" in driver.page_source

    def test_add_dummy(self, driver, w, ctx):
        inp = driver.find_element(By.CSS_SELECTOR, "input[name='display_name']")
        inp.clear()
        inp.send_keys("Offline Alice")
        driver.find_element(By.ID, "btn-add-dummy").click()
        time.sleep(1)
        assert "Offline Alice" in driver.page_source

    def test_onboarding_hint_hidden_with_dummy(self, driver, w, ctx):
        assert "How Buddies work:" not in driver.page_source

    def test_dummy_appears_in_expense_form(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        assert "Expense assignment" in driver.page_source
        assert "Offline Alice" in driver.page_source

    def test_kick_dummy_no_debt_shows_confirm(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "a[href*='kick']").click()
        time.sleep(1)
        assert "kick" in driver.current_url
        assert "Remove" in driver.page_source

    def test_kick_dummy_confirm_removes_dummy(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-confirm-kick").click()
        time.sleep(1)
        assert "Offline Alice" not in driver.page_source
        assert "/buddies/" in driver.current_url

    def test_onboarding_hint_shown_again_after_kick(self, driver, w, ctx):
        assert "How Buddies work:" in driver.page_source


# ---------------------------------------------------------------------------
# Kick dummy with outstanding debt
# ---------------------------------------------------------------------------

class TestDummyKickWithDebt:
    """Kick a dummy that has a shared expense: confirm dialog must show balance."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Deborah", last_name="Debtor")
        email = c["email"]
        dummy_id = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Debt Dummy'); "
            f"print(d.pk)"
        )
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"create_expense(owning_feuser=u, title='Debt Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('100.00'), "
            f"  date_due=None, settled=False, "
            f"  buddy_spendings=[{{'type': 'dummy', 'id': {dummy_id}, 'share_percent': 50}}])"
        )
        c["dummy_id"] = int(dummy_id)
        yield c
        cleanup_user(c["email"])

    def test_dummy_with_debt_shown_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Debt Dummy" in driver.page_source

    def test_balance_amount_in_page(self, driver, w, ctx):
        # The form's data-confirm contains the balance amount (50.00 = 50% of 100)
        assert "50.00" in driver.page_source

    def test_kick_dummy_with_debt_shows_confirm_page(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "a[href*='kick']").click()
        time.sleep(1)
        assert "kick" in driver.current_url
        assert "50.00" in driver.page_source, \
            "Confirmation page must show the outstanding balance"

    def test_kick_dummy_confirm_removes_dummy(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-confirm-kick").click()
        time.sleep(1)
        assert "Debt Dummy" not in driver.page_source
        assert "/buddies/" in driver.current_url


# ---------------------------------------------------------------------------
# is_dummy=True expense: hidden from API, visible on buddies summary
# ---------------------------------------------------------------------------

class TestIsDummyExpenseVisibility:
    """is_dummy=True expenses are invisible in the expense API but shown on summary."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Vera", last_name="Visible")
        email = c["email"]
        _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Payer Dummy'); "
            f"Expense.objects.create(owning_feuser=u, title='Hidden Payer Expense', "
            f"  type='expense', value=Decimal('50.00'), settled=False, "
            f"  is_dummy=True, upfront_payee_dummy=d)"
        )
        yield c
        cleanup_user(c["email"])

    def test_not_in_expense_api(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Hidden Payer Expense"})
        assert resp.status_code == 200
        assert not any(e["title"] == "Hidden Payer Expense"
                       for e in resp.json()["expenses"]), \
            "is_dummy expense must not appear in the expense API"

    def test_visible_on_buddy_summary_page(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Hidden Payer Expense" in driver.page_source, \
            "is_dummy expense must be visible on the buddy summary page"

    def test_payer_name_shown_on_summary_page(self, driver, w, ctx):
        assert "Payer Dummy" in driver.page_source, \
            "Upfront payer dummy name must appear as the 'Paid by' person"
