"""
Spending over time (line chart) and tag distribution (bar chart) on the
project detail page. Both charts use Chart.js via project_charts.js and
are visible regardless of whether the project is solo or multi-member.
"""
import time
from datetime import date, timedelta

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_group, _add_group_member, _create_group_expense


def _get_group_uid(group_id: int) -> str:
    return _shell(
        f"from buddies.models import Project; "
        f"print(Project.objects.get(pk={group_id}).uid)"
    )


def _create_solo_expense(owner_email: str, group_id: int, title: str,
                          value: str = "50.00", tag_title: str = "") -> str:
    """Create an approved project expense with the solo pattern (100% BuddySpending for creator)."""
    tag_part = (
        f"tag, _ = Tag.objects.get_or_create(owning_feuser=a, title='{tag_title}'); "
        f"e.tags.add(tag); "
    ) if tag_title else ""
    return _shell(
        f"from budget.models import Expense, Tag; "
        f"from buddies.models import Project, BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"a = FeUser.objects.get(email='{owner_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"e = Expense.objects.create(owning_feuser=a, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved=True, project=g); "
        f"{tag_part}"
        f"BuddySpending.objects.create(expense=e, participant_feuser=a, share_percent=Decimal('100')); "
        f"print(e.pk)"
    )


def _create_expense_with_tag(owner_email: str, group_id: int,
                              participant_email: str, tag_title: str,
                              value: str = "80.00", share: str = "50.0") -> str:
    """Create an approved project expense whose owner has a named tag on it."""
    return _shell(
        f"from budget.models import Expense, Tag; "
        f"from buddies.models import Project, BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"a = FeUser.objects.get(email='{owner_email}'); "
        f"b = FeUser.objects.get(email='{participant_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"tag, _ = Tag.objects.get_or_create(owning_feuser=a, title='{tag_title}'); "
        f"e = Expense.objects.create(owning_feuser=a, title='Tagged Expense', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved=True, project=g); "
        f"e.tags.add(tag); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=b, "
        f"  share_percent=Decimal('{share}')); "
        f"print(e.pk)"
    )


class TestSpendingOverTimeChart:
    """Line chart appears on a multi-member project with approved expenses."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin  = setup_user(driver, w, first_name="LineChart", last_name="Admin")
        member = setup_user(None, None, first_name="LineChart", last_name="Member")
        gid = int(_create_group(admin["email"], "LineChart Group"))
        _add_group_member(gid, member["email"])
        _create_group_expense(
            admin_email=admin["email"],
            participant_email=member["email"],
            group_id=gid,
            title="LC Expense A",
            value="120.00",
            share="50.0",
        )
        _create_group_expense(
            admin_email=member["email"],
            participant_email=admin["email"],
            group_id=gid,
            title="LC Expense B",
            value="40.00",
            share="25.0",
        )
        uid = _get_group_uid(gid)
        yield {"admin": admin, "member": member, "gid": gid, "uid": uid}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_spending_over_time_section_visible(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['uid']}/"))
        time.sleep(1)
        assert "Spending over time" in driver.page_source, \
            "Spending over time section must appear when project has approved non-settlement expenses"

    def test_line_chart_canvas_present(self, driver, w, ctx):
        canvas = driver.find_element(By.ID, "proj-spending-line")
        assert canvas is not None, "proj-spending-line canvas must be present"

    def test_project_charts_data_injected(self, driver, w, ctx):
        has_data = driver.execute_script(
            "return !!(window.PROJECT_CHARTS && window.PROJECT_CHARTS.spendingOverTime)"
        )
        assert has_data, "window.PROJECT_CHARTS.spendingOverTime must be set"

    def test_line_chart_series_include_total_and_members(self, driver, w, ctx):
        series_labels = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.spendingOverTime; "
            "return d ? d.series.map(function(s){return s.label;}) : [];"
        )
        assert "Total" in series_labels, "spendingOverTime must have a Total series"
        assert "You" in series_labels, "spendingOverTime must have a You series for the viewing member"

    def test_chart_js_rendered_line(self, driver, w, ctx):
        # Chart.js draws onto the canvas — check it has a non-zero intrinsic size
        height = driver.execute_script(
            "var c = document.getElementById('proj-spending-line'); "
            "return c ? c.offsetHeight : 0;"
        )
        assert height > 0, "proj-spending-line canvas must have non-zero height after Chart.js renders"


def _create_solo_expense_on_date(owner_email: str, group_id: int, title: str,
                                  date_due: str, value: str = "50.00") -> str:
    """Create an approved project expense with an explicit date_due (YYYY-MM-DD)."""
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import Project, BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"a = FeUser.objects.get(email='{owner_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"e = Expense.objects.create(owning_feuser=a, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved=True, project=g, date_due='{date_due}'); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=a, share_percent=Decimal('100')); "
        f"print(e.pk)"
    )


class TestSpendingOverTimeOldProject:
    """On an old project, the chart's x-axis must span first-to-last expense date,
    not first expense to today (which used to stretch the line flat for old projects)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="OldLine", last_name="Admin")
        gid = int(_create_group(admin["email"], "OldLine Project"))
        first_date = (date.today() - timedelta(days=400)).isoformat()
        last_date = (date.today() - timedelta(days=390)).isoformat()
        _create_solo_expense_on_date(admin["email"], gid, "Old Expense A", first_date)
        _create_solo_expense_on_date(admin["email"], gid, "Old Expense B", last_date)
        uid = _get_group_uid(gid)
        yield {"admin": admin, "gid": gid, "uid": uid, "first_date": first_date, "last_date": last_date}
        cleanup_user(admin["email"])

    def test_chart_last_label_is_last_expense_date_not_today(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        # The date-range picker defaults to the current financial month (shared
        # site-wide), which would exclude these ~400-day-old expenses entirely.
        # Pass an explicit range covering them through today via URL params
        # (date-range.js reads date_from/date_to from the URL first) so the
        # chart actually has data to prove it stops at the last expense.
        today = date.today().isoformat()
        driver.get(_url(f"/projects/{ctx['uid']}/?date_from={ctx['first_date']}&date_to={today}"))
        time.sleep(1)
        labels = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.spendingOverTime; "
            "return d ? d.labels : [];"
        )
        assert labels, "spendingOverTime must have labels for an old project with expenses"
        assert labels[-1] == ctx["last_date"], (
            f"Last chart label must be the last expense date ({ctx['last_date']}), "
            f"not today, got {labels[-1]}"
        )
        assert date.today().isoformat() not in labels, \
            "Chart must not include today's date when no expense was made today"


class TestTagDistributionChart:
    """Bar chart appears when the viewing feuser has tags on their project expenses."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin  = setup_user(driver, w, first_name="TagChart", last_name="Admin")
        member = setup_user(None, None, first_name="TagChart", last_name="Member")
        gid = int(_create_group(admin["email"], "TagChart Group"))
        _add_group_member(gid, member["email"])
        _create_expense_with_tag(
            owner_email=admin["email"],
            group_id=gid,
            participant_email=member["email"],
            tag_title="Camping",
            value="90.00",
            share="50.0",
        )
        uid = _get_group_uid(gid)
        yield {"admin": admin, "member": member, "gid": gid, "uid": uid}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_tag_chart_section_visible(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['uid']}/"))
        time.sleep(1)
        assert "Project spending by tag" in driver.page_source, \
            "Project spending by tag section must appear when feuser has tags on their expenses"

    def test_tag_bar_canvas_present(self, driver, w, ctx):
        canvas = driver.find_element(By.ID, "proj-tag-bar")
        assert canvas is not None, "proj-tag-bar canvas must be present"

    def test_tag_dist_data_injected(self, driver, w, ctx):
        has_data = driver.execute_script(
            "return !!(window.PROJECT_CHARTS && window.PROJECT_CHARTS.tagDist)"
        )
        assert has_data, "window.PROJECT_CHARTS.tagDist must be set"

    def test_tag_dist_includes_named_tag(self, driver, w, ctx):
        labels = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.tagDist; "
            "return d ? d.labels : [];"
        )
        assert "Camping" in labels, "tagDist labels must include the 'Camping' tag"

    def test_tag_value_is_full_expense_amount(self, driver, w, ctx):
        # The expense is 90.00 total; tag value must be the full project spend, not feuser's share
        labels = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.tagDist; "
            "return d ? d.labels : [];"
        )
        values = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.tagDist; "
            "return d ? d.values : [];"
        )
        idx = labels.index("Camping") if "Camping" in labels else -1
        assert idx >= 0, "Camping tag must be present"
        assert abs(values[idx] - 90.0) < 0.01, \
            f"Camping tag value must equal the full expense amount 90.00, got {values[idx]}"

    def test_member_view_sees_only_untagged(self, driver, w, ctx):
        # Member has no overlay tags: expense falls into (untagged) at full expense value
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/projects/{ctx['uid']}/"))
        time.sleep(1)
        labels = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.tagDist; "
            "return d ? d.labels : [];"
        )
        values = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.tagDist; "
            "return d ? d.values : [];"
        )
        assert labels == ["(untagged)"], \
            "Member with no overlay tags must see only (untagged) in tagDist"
        assert abs(values[0] - 90.0) < 0.01, \
            f"(untagged) value must equal the full expense amount 90.00, got {values[0]}"


class TestSoloProjectSpendingChart:
    """Solo project shows spending over time chart (but no pie chart)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="SoloLine", last_name="Admin")
        gid = int(_create_group(admin["email"], "SoloLine Project"))
        _create_solo_expense(admin["email"], gid, "Solo Trip Cost",
                             value="75.00", tag_title="Travel")
        uid = _get_group_uid(gid)
        yield {"admin": admin, "gid": gid, "uid": uid}
        cleanup_user(admin["email"])

    def test_solo_spending_over_time_visible(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['uid']}/"))
        time.sleep(1)
        assert "Spending over time" in driver.page_source, \
            "Solo project must show Spending over time chart when it has expenses"

    def test_solo_total_spending_label_visible(self, driver, w, ctx):
        assert "Total:" in driver.page_source, \
            "Solo project must show the total spending amount in the Spending over time section"

    def test_solo_total_spending_value(self, driver, w, ctx):
        assert "75.00" in driver.page_source, \
            "Solo project must display the total spending value (75.00)"

    def test_solo_pie_chart_absent(self, driver, w, ctx):
        assert "Spending breakdown" not in driver.page_source, \
            "Solo project must never show the multi-member pie chart"

    def test_solo_tag_chart_visible(self, driver, w, ctx):
        assert "Project spending by tag" in driver.page_source, \
            "Solo project must show tag distribution chart when expenses have tags"

    def test_solo_tag_dist_reflects_full_expense_amount(self, driver, w, ctx):
        # Tag value is the full expense amount (75.00), not a participation fraction
        labels = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.tagDist; "
            "return d ? d.labels : [];"
        )
        values = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.tagDist; "
            "return d ? d.values : [];"
        )
        assert "Travel" in labels, "tagDist must include the 'Travel' tag for solo expense"
        idx = labels.index("Travel")
        assert abs(values[idx] - 75.0) < 0.01, \
            f"Travel tag value must equal full project expense amount 75.00, got {values[idx]}"

    def test_solo_line_canvas_rendered(self, driver, w, ctx):
        height = driver.execute_script(
            "var c = document.getElementById('proj-spending-line'); "
            "return c ? c.offsetHeight : 0;"
        )
        assert height > 0, "proj-spending-line canvas must render for solo project with expenses"

    def test_solo_total_series_has_spending(self, driver, w, ctx):
        total_values = driver.execute_script(
            "var d = window.PROJECT_CHARTS && window.PROJECT_CHARTS.spendingOverTime; "
            "if (!d) return []; "
            "var t = d.series.find(function(s){return s.label === 'Total';}); "
            "return t ? t.values : [];"
        )
        total = sum(total_values)
        assert abs(total - 75.0) < 0.01, \
            f"Total series must sum to 75.00 (the solo expense value), got {total}"
