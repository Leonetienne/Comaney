"""
Actual buddy kick flows: without debt (immediate via confirm dialog),
with debt (confirm shows balance), and post-kick state for the kicked user.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_buddy_link, _get_pk, _confirm


# ---------------------------------------------------------------------------
# Kick without debt
# ---------------------------------------------------------------------------

class TestKickActualBuddyNoDebt:
    """Kick buddy with zero balance: confirm dialog, then buddy gone."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Kira", last_name="Kicker")
        b = setup_user(None, None, first_name="Victor", last_name="Kicked")
        _create_buddy_link(a["email"], b["email"])
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_buddy_visible_before_kick(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert ctx["b"]["email"] in driver.page_source

    def test_kick_shows_confirm_dialog(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='link'][action*='kick'] button[type=submit]").click()
        time.sleep(0.5)
        assert driver.find_element(By.ID, "cdialog-ok").is_displayed()

    def test_confirm_removes_buddy(self, driver, w, ctx):
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url
        assert ctx["b"]["email"] not in driver.page_source

    def test_no_buddy_link_in_db(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import BuddyLink; "
            f"from feusers.models import FeUser; "
            f"from django.db.models import Q; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(BuddyLink.objects.filter(Q(user_a=a,user_b=b)|Q(user_a=b,user_b=a)).count())"
        )
        assert count == "0"


# ---------------------------------------------------------------------------
# Kick with debt: confirm dialog shows balance, kick still works
# ---------------------------------------------------------------------------

class TestKickActualBuddyWithDebt:
    """Kick buddy with outstanding debt: balance shown in confirm, kick succeeds."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Kira", last_name="DebtKicker")
        b = setup_user(None, None, first_name="Victor", last_name="DebtKicked")
        _create_buddy_link(a["email"], b["email"])
        b_pk = _get_pk(b["email"])
        # A paid 200; B owes 50% = 100
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"create_expense(owning_feuser=u, title='Kick Debt Exp', "
            f"  type=TransactionType.EXPENSE, value=Decimal('200.00'), "
            f"  date_due=None, settled=False, "
            f"  buddy_spendings=[{{'type': 'feuser', 'id': {b_pk}, 'share_percent': 50}}])"
        )
        yield {"a": a, "b": b, "b_pk": int(b_pk)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_balance_visible_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        # Balance = 100.00 (50% of 200)
        assert "100.00" in driver.page_source

    def test_kick_dialog_contains_balance(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='link'][action*='kick'] button[type=submit]").click()
        time.sleep(0.5)
        dialog_msg = driver.find_element(By.ID, "cdialog-msg").text
        assert "100.00" in dialog_msg, \
            f"Dialog must mention the balance, got: {dialog_msg!r}"

    def test_confirm_removes_buddy_with_debt(self, driver, w, ctx):
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert ctx["b"]["email"] not in driver.page_source
        assert "/buddies/" in driver.current_url

    def test_kicked_b_has_ghost_dummy_for_a(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        # A ghost dummy with A's display name must exist on B's page
        a_display = "Kira DebtKicker"
        assert a_display in driver.page_source, \
            "Kicked user B must see a ghost dummy representing A"

    def test_kicked_b_sees_cloned_expense(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Kick Debt Exp" in driver.page_source, \
            "Kicked user B must see the cloned expense history"
