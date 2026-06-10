"""
Group spending breakdown pie chart: section visibility, totals, SVG rendering,
and bgs-card total spending display on the buddy summary page.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk,
    _create_group, _add_group_member, _create_group_expense,
)


def _get_group_uid(group_id: int) -> str:
    return _shell(
        f"from buddies.models import Project; "
        f"print(Project.objects.get(pk={group_id}).uid)"
    )


class TestGroupSpendingChart:
    """Spending breakdown section and pie chart render on the project's Insights tab."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Chart", last_name="Admin")
        member = setup_user(None, None, first_name="Chart", last_name="Member")
        _create_buddy_link(admin["email"], member["email"])
        gid = int(_create_group(admin["email"], "Chart Test Group"))
        _add_group_member(gid, member["email"])
        # Create two approved non-settlement expenses so both members have spending
        _create_group_expense(
            admin_email=admin["email"],
            participant_email=member["email"],
            group_id=gid,
            title="Chart Expense A",
            value="100.00",
            share="40.0",
        )
        _create_group_expense(
            admin_email=member["email"],
            participant_email=admin["email"],
            group_id=gid,
            title="Chart Expense B",
            value="60.00",
            share="50.0",
        )
        uid = _get_group_uid(gid)
        yield {"admin": admin, "member": member, "gid": gid, "uid": uid}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_spending_section_visible(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['uid']}/insights/"))
        time.sleep(1)
        assert "Spending breakdown" in driver.page_source, \
            "Spending breakdown section must appear when group has approved non-settlement expenses"

    def test_group_total_displayed(self, driver, w, ctx):
        # The pie legend shows each member's own upfront-paid amount, not a
        # combined group total: admin paid 100.00 (Expense A), member paid
        # 60.00 (Expense B).
        legend = driver.find_element(By.ID, "group-spending-legend")
        assert "100.00" in legend.text and "60.00" in legend.text, \
            "Legend must show each member's individual spending amount"

    def test_pie_svg_rendered(self, driver, w, ctx):
        container = driver.find_element(By.ID, "group-spending-pie")
        svg = container.find_element(By.TAG_NAME, "svg")
        assert svg is not None, "SVG pie chart must be rendered inside #group-spending-pie"

    def test_legend_shows_members(self, driver, w, ctx):
        legend_rows = driver.find_elements(By.CLASS_NAME, "pie-legend-row")
        assert len(legend_rows) >= 2, \
            "Legend must show at least 2 rows (one per member with spending)"

    def test_legend_shows_amounts(self, driver, w, ctx):
        legend = driver.find_element(By.ID, "group-spending-legend")
        text = legend.text
        # Pie chart shows upfront payments only: admin paid 100, member paid 60
        assert "%" in text, "Legend must include percentage values"

    def test_svg_has_clip_paths(self, driver, w, ctx):
        clip_count = driver.execute_script(
            "return document.querySelectorAll('#group-spending-pie clipPath').length"
        )
        assert clip_count >= 2, \
            "SVG must have at least 2 clipPath elements (one per member with spending)"


class TestGroupSpendingChartHidden:
    """Spending breakdown section is absent when all approved expenses are settlements."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="NoChart", last_name="Admin")
        member = setup_user(None, None, first_name="NoChart", last_name="Member")
        _create_buddy_link(admin["email"], member["email"])
        gid = int(_create_group(admin["email"], "No Chart Group"))
        _add_group_member(gid, member["email"])
        # Only create a settlement expense
        member_pk = int(_get_pk(member["email"]))
        _shell(
            f"from budget.models import Expense; from buddies.models import BuddySpending, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"a = FeUser.objects.get(email='{admin['email']}'); "
            f"b = FeUser.objects.get(pk={member_pk}); "
            f"g = Project.objects.get(pk={gid}); "
            f"e = Expense.objects.create(owning_feuser=a, title='Settlement', "
            f"  type='expense', value=Decimal('50.00'), settled=True, "
            f"  is_buddies_settlement=True, buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=b, share_percent=Decimal('100.0')); "
            f"print(e.pk)"
        )
        uid = _get_group_uid(gid)
        yield {"admin": admin, "uid": uid}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_spending_section_absent(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['uid']}/insights/"))
        time.sleep(2)  # Wait for AJAX charts to load
        is_hidden = driver.execute_script(
            "var s = document.getElementById('section-spending-breakdown');"
            "if (!s) return true;"
            "return getComputedStyle(s).display === 'none';"
        )
        assert is_hidden, \
            "Spending breakdown section must not be visible when group only has settlement expenses"


class TestBgsCardTotalSpending:
    """Total group spending is shown on the bgs-card in the buddy summary page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="BgsTotal", last_name="Admin")
        member = setup_user(None, None, first_name="BgsTotal", last_name="Member")
        _create_buddy_link(admin["email"], member["email"])
        gid = int(_create_group(admin["email"], "BgsTotal Group"))
        _add_group_member(gid, member["email"])
        _create_group_expense(
            admin_email=admin["email"],
            participant_email=member["email"],
            group_id=gid,
            title="BgsTotal Expense",
            value="80.00",
            share="50.0",
        )
        yield {"admin": admin}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_bgs_card_shows_total(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url("/projects/"))
        time.sleep(1)
        # Total spending is rendered as a .bgs-stat row with label "Total spending"
        stat_labels = driver.find_elements(By.CLASS_NAME, "bgs-stat-label")
        total_labels = [el for el in stat_labels if "Total spending" in el.text]
        assert len(total_labels) >= 1, \
            "At least one bgs-card must show a 'Total spending' stat row"

    def test_bgs_card_total_value(self, driver, w, ctx):
        # Find all .bgs-stat rows that contain "Total spending" and check the value
        stat_rows = driver.find_elements(By.CLASS_NAME, "bgs-stat")
        total_values = []
        for row in stat_rows:
            try:
                label = row.find_element(By.CLASS_NAME, "bgs-stat-label")
                value = row.find_element(By.CLASS_NAME, "bgs-stat-value")
                if "Total spending" in label.text:
                    total_values.append(value.text)
            except Exception:
                pass
        assert any("80.00" in v for v in total_values), \
            "The bgs-card must display the group total spending (80.00) in the Total spending stat"


class TestPieChartClickThrough:
    """Each pie slice/legend row carries a payer= filter query and is
    clickable, sending the browser to the project's expense list filtered
    to that person's expenses."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Piechart", last_name="Payer")
        member = setup_user(None, None, first_name="Piechart", last_name="Member")
        _create_buddy_link(admin["email"], member["email"])
        gid = int(_create_group(admin["email"], "Pie Click Group"))
        _add_group_member(gid, member["email"])
        _create_group_expense(
            admin_email=admin["email"],
            participant_email=member["email"],
            group_id=gid,
            title="Pie Click Expense",
            value="70.00",
            share="50.0",
        )
        uid = _get_group_uid(gid)
        yield {"admin": admin, "member": member, "gid": gid, "uid": uid}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_spending_pie_data_injected(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['uid']}/insights/"))
        time.sleep(2)
        has_data = driver.execute_script(
            "return !!(window.PROJECT_CHARTS && window.PROJECT_CHARTS.spendingPie)"
        )
        assert has_data, "window.PROJECT_CHARTS.spendingPie must be set"

    def test_pie_member_query_is_full_name_payer_filter(self, driver, w, ctx):
        queries = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.spendingPie; "
            "return d ? d.map(function(m){return m.query;}) : [];"
        )
        assert 'payer="Piechart Payer"' in queries, \
            f"Pie data must carry a payer= filter query for the admin's full name, got {queries}"

    def test_click_pie_slice_navigates_to_expense_list(self, driver, w, ctx):
        # The destination page strips ?q= from the URL right after reading it
        # (see project_detail.html), so the proof of a successful click-through
        # is the pre-filled search box, not a lingering q= in the URL.
        hit_paths = driver.find_elements(By.CSS_SELECTOR, "#group-spending-pie svg path[fill='transparent']")
        assert hit_paths, "Pie chart must render at least one clickable slice"
        driver.execute_script(
            "arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));", hit_paths[0]
        )
        time.sleep(1)
        assert "/insights/" not in driver.current_url, \
            "Clicking a pie slice must navigate away from the Insights tab to the expense list"
        search_value = driver.find_element(By.ID, "proj-exp-search").get_attribute("value")
        assert search_value.startswith('payer="'), \
            f"Clicking a pie slice must pre-fill the expense search box with a payer= filter, got '{search_value}'"

    def test_click_pie_slice_strips_q_param_from_url(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['uid']}/insights/"))
        time.sleep(2)
        hit_paths = driver.find_elements(By.CSS_SELECTOR, "#group-spending-pie svg path[fill='transparent']")
        assert hit_paths, "Pie chart must render at least one clickable slice"
        driver.execute_script(
            "arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));", hit_paths[0]
        )
        time.sleep(1)
        assert "q=" not in driver.current_url, \
            f"?q= must be stripped from the URL right after page load, got '{driver.current_url}'"

    def test_click_legend_row_navigates_to_expense_list(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['uid']}/insights/"))
        time.sleep(2)
        rows = driver.find_elements(By.CLASS_NAME, "pie-legend-row")
        assert rows, "Legend must render at least one row"
        driver.execute_script("arguments[0].click();", rows[0])
        time.sleep(1)
        search_value = driver.find_element(By.ID, "proj-exp-search").get_attribute("value")
        assert search_value.startswith('payer="'), \
            f"Clicking a legend row must pre-fill the expense search box with a payer= filter, got '{search_value}'"

    def test_payer_filter_matches_only_that_payer(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['uid']}/?q=" + 'payer%3D%22Piechart%20Payer%22'))
        time.sleep(1)
        search_value = driver.find_element(By.ID, "proj-exp-search").get_attribute("value")
        assert search_value == 'payer="Piechart Payer"', \
            f"?q= must pre-fill the expense search box, got '{search_value}'"
        assert "Pie Click Expense" in driver.page_source, \
            "Expense list must show the admin's expense once the payer= filter from the URL is applied"

    def test_payer_filter_excludes_other_payer(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['uid']}/?q=" + 'payer%3D%22Piechart%20Member%22'))
        time.sleep(1)
        assert "Pie Click Expense" not in driver.page_source, \
            "payer= filter for the member must not show the expense paid by the admin"
