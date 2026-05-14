"""
Debt clearance after settlement: verifies that settling with the correct amount
actually reduces the remaining balance to zero.

Three scenarios:

1. Direct full settlement:
   A owes B 50.00 exactly. A settles 50.00. B confirms. Balance = 0 ("Settled").

2. Direct partial then remainder:
   A owes B 100.00. A first settles 60.00 (B confirms) — remaining = 40.00.
   A then settles the remaining 40.00 (B confirms) — balance = 0.

3. Group full settlement:
   Member owes admin 80.00. Member settles 80.00. Admin confirms.
   Group page shows "You are all settled up." and "Everyone is settled up."
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _confirm,
    _create_buddy_link, _get_pk,
    _create_personal_expense_with_buddy,
    _create_group, _add_group_member, _create_group_expense,
)


# ---------------------------------------------------------------------------
# Direct full settlement: remaining debt = 0
# ---------------------------------------------------------------------------

class TestDirectFullSettlementZeroBalance:
    """A owes B exactly 50.00; after settling and B confirming, balance = 0."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Fern", last_name="Debtor")
        b = setup_user(None, None, first_name="Gil", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        # B paid 100; A owes 50% = 50.00
        _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Full Clear Source",
            value="100.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_initial_debt_shown_correctly(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR, ".settle-amount-input")
        assert inp.get_attribute("value") == "50.00", \
            "Pre-filled amount must equal the exact debt of 50.00"

    def test_settle_exact_amount(self, driver, w, ctx):
        driver.find_element(
            By.CSS_SELECTOR, ".direct-settle-form button[type=submit]"
        ).click()
        _confirm(driver)
        time.sleep(1)

    def test_creditor_confirms(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        driver.find_element(
            By.CSS_SELECTOR, "form[action*='/approve-settlement/'] button[type=submit]"
        ).click()
        time.sleep(1)

    def test_balance_zero_on_buddies_page(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        # When net = 0 the template renders a span with "Settled" inside balance-zero div
        assert "Settled" in driver.page_source, \
            "Buddies page must show 'Settled' next to Gil once debt is fully cleared"
        # And there must be no negative balance shown for Gil
        src = driver.page_source
        assert "You owe them" not in src, \
            "Must not show 'You owe them' once balance = 0"

    def test_no_settle_up_section_on_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Settle Up" not in driver.page_source, \
            "Settle Up section must be absent when remaining debt = 0"

    def test_net_debt_zero_via_shell(self, driver, w, ctx):
        net = _shell(
            f"from buddies.services import BuddyQueryService; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(BuddyQueryService.get_net_debt(a, buddy_feuser=b))"
        )
        assert float(net) == 0.0, \
            f"Net debt must be exactly 0 after full settlement confirmed, got {net}"


# ---------------------------------------------------------------------------
# Direct partial then full settlement: remaining decrements correctly
# ---------------------------------------------------------------------------

class TestDirectPartialThenFullSettlement:
    """A owes B 100.00; settles 60 first (40 remains), then settles remaining 40."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Hugo", last_name="Partial")
        b = setup_user(None, None, first_name="Ida", last_name="PartialCred")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        # B paid 200; A owes 50% = 100.00
        _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Partial Clear Source",
            value="200.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_initial_debt_is_100(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR, ".settle-amount-input")
        assert inp.get_attribute("value") == "100.00", \
            "Pre-filled amount must be 100.00 (full debt)"

    def test_submit_partial_settlement_of_60(self, driver, w, ctx):
        inp = driver.find_element(By.CSS_SELECTOR, ".settle-amount-input")
        inp.clear()
        inp.send_keys("60.00")
        driver.find_element(
            By.CSS_SELECTOR, ".direct-settle-form button[type=submit]"
        ).click()
        _confirm(driver)
        time.sleep(1)

    def test_creditor_confirms_partial(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        driver.find_element(
            By.CSS_SELECTOR, "form[action*='/approve-settlement/'] button[type=submit]"
        ).click()
        time.sleep(1)

    def test_remaining_debt_is_40(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Settle Up" in driver.page_source, \
            "Settle Up section must still appear: 40.00 remains unpaid"
        inp = driver.find_element(By.CSS_SELECTOR, ".settle-amount-input")
        assert inp.get_attribute("value") == "40.00", \
            "Remaining debt must be 40.00 after the 60.00 partial settlement"

    def test_balance_shows_negative_40_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        # Template renders: <span title="You owe them">-€40.00</span>
        assert "You owe them" in driver.page_source, \
            "Buddies page must show 'You owe them' while 40.00 is still owed"
        assert "40.00" in driver.page_source, \
            "Remaining 40.00 must appear on /buddies/ after the partial settlement is confirmed"

    def test_settle_remaining_40(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        driver.find_element(
            By.CSS_SELECTOR, ".direct-settle-form button[type=submit]"
        ).click()
        _confirm(driver)
        time.sleep(1)

    def test_creditor_confirms_remainder(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        driver.find_element(
            By.CSS_SELECTOR, "form[action*='/approve-settlement/'] button[type=submit]"
        ).click()
        time.sleep(1)

    def test_debt_fully_cleared_no_settle_up(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Settle Up" not in driver.page_source, \
            "Settle Up section must be absent once the remaining 40.00 is also confirmed"

    def test_balance_settled_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Settled" in driver.page_source, \
            "Buddies page must show 'Settled' next to Ida after both partial settlements clear"
        assert "You owe them" not in driver.page_source, \
            "Must not show 'You owe them' once balance = 0"


# ---------------------------------------------------------------------------
# Group full settlement: remaining debt = 0 on group page
# ---------------------------------------------------------------------------

class TestGroupFullSettlementZeroBalance:
    """Member owes admin 80.00; after settling and admin confirming, group shows settled."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Jane", last_name="GroupCred")
        member = setup_user(driver, w, first_name="Karl", last_name="GroupDeb")
        group_id = _create_group(admin["email"], "ZeroBalGroup")
        _add_group_member(group_id, member["email"])
        # Admin paid 160; member owes 50% = 80.00
        _create_group_expense(
            admin_email=admin["email"],
            participant_email=member["email"],
            group_id=group_id,
            title="Zero Bal Source",
            value="160.00",
            share="50.0",
        )
        yield {"admin": admin, "member": member, "group_id": group_id}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_member_initial_debt_shown(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "80.00" in driver.page_source, \
            "Member must see 80.00 owed before settlement"
        assert "Jane" in driver.page_source, \
            "Creditor's name must appear in the balance section"

    def test_member_settles_exact_amount(self, driver, w, ctx):
        driver.find_element(
            By.CSS_SELECTOR, "form[action*='/settle-individual/'] button[type=submit]"
        ).click()
        _confirm(driver)
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower()

    def test_admin_confirms_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        driver.find_element(
            By.CSS_SELECTOR, "form[action*='/approve-settlement/'] button[type=submit]"
        ).click()
        time.sleep(1)
        assert "confirmed" in driver.page_source.lower()

    def test_member_sees_all_settled_up_on_group_page(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "You are all settled up." in driver.page_source, \
            "Group page must show 'You are all settled up.' when member's balance = 0"

    def test_group_shows_no_transfers_needed(self, driver, w, ctx):
        assert "Everyone is settled up. No transfers needed." in driver.page_source, \
            "Group page must show 'No transfers needed.' once all debts are cleared"

    def test_no_settle_up_for_member_on_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Settle Up" not in driver.page_source, \
            "Settle Up section must not appear on buddy summary when group debt = 0"

    def test_admin_balance_zero_on_group_page(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Everyone is settled up. No transfers needed." in driver.page_source, \
            "Admin must also see 'No transfers needed.' once all debts are cleared"
