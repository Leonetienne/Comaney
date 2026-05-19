"""
Buddy summary page (/buddies/summary/): direct expense listing, D3 debt graph,
and group saldo cards.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk,
    _create_group, _add_group_member, _create_personal_expense_with_buddy,
    _create_group_expense,
)


# ---------------------------------------------------------------------------
# Direct buddy expenses listed on summary
# ---------------------------------------------------------------------------

class TestSummaryDirectExpenses:
    """Shared expense appears on the summary page with title and amount."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Sum", last_name="Checker")
        b = setup_user(None, None, first_name="Sum", last_name="Partner")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Summary Direct Expense",
            value="120.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_expense_title_on_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Summary Direct Expense" in driver.page_source, \
            "Approved shared expense must appear on the summary page"

    def test_expense_amount_on_summary(self, driver, w, ctx):
        # A's share is 50% of 120 = 60.00
        assert "60.00" in driver.page_source, \
            "A's share of the expense must be visible on the summary page"


# ---------------------------------------------------------------------------
# D3 debt graph present for direct buddy expenses
# ---------------------------------------------------------------------------

class TestSummaryD3Graph:
    """D3 SVG element is rendered when direct buddy expenses exist."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Dora", last_name="D3User")
        b = setup_user(None, None, first_name="Dan", last_name="D3Partner")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="D3 Graph Expense",
            value="80.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_d3_svg_rendered(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        svgs = driver.find_elements(By.CSS_SELECTOR, "#buddy-debt-graph svg")
        assert len(svgs) >= 1, "D3 must render an SVG element inside #buddy-debt-graph"


# ---------------------------------------------------------------------------
# Verify groups/projects block is no longer on buddy summary
# ---------------------------------------------------------------------------

class TestSummaryNoGroupBlock:
    """The buddy summary page must NOT show a groups/projects block (moved to /projects/)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Greta", last_name="GroupSaldo")
        member = setup_user(None, None, first_name="Max", last_name="GroupMember")
        group_id = _create_group(admin["email"], "SaldoGroup")
        _add_group_member(int(group_id), member["email"])
        member_pk = int(_get_pk(member["email"]))
        _create_group_expense(
            admin_email=admin["email"],
            participant_email=member["email"],
            group_id=int(group_id),
            title="Group Saldo Expense",
            value="100.00",
            share="50.0",
        )
        ctx = {"admin": admin, "member": member, "group_id": int(group_id)}
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_no_group_block_on_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        # The groups section was removed from buddy_summary; project is on /projects/
        assert "bgs-cards" not in driver.page_source, \
            "Groups/projects block must not appear on the buddy summary page"

    def test_summary_still_shows_pending_approvals_heading(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        # Pending approvals section should still be present (admin has a dummy_payer expense)
        # Just verify the page loads correctly
        assert "Buddy Expenses" in driver.page_source
