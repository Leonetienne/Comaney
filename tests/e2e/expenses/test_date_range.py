"""Date range selector on expenses list, dashboard, and buddy summary.
Project detail pages have no date-range selector; they always show all-time data.
"""
import subprocess
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, api_post, server_today, DOCKER_WEB


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    today = server_today()
    api_post("/api/v1/expenses/", c, json={
        "title": "DateRange Today Exp",
        "value": "10.00",
        "type": "expense",
        "date_due": today,
        "settled": True,
    })
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def project_url(driver, w, ctx):
    """Create a project via the UI and return its detail URL."""
    driver.get(_url("/projects/"))
    time.sleep(2)
    driver.execute_script(
        "document.getElementById('project-name').value = 'DateRange Test Project';"
    )
    driver.find_element(By.ID, "btn-create-project").click()
    time.sleep(2)
    url = driver.current_url
    yield url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_preset(driver, key):
    """Pick a preset from the dropdown via JS (safe on minimized windows)."""
    driver.execute_script(
        f"var sel = document.getElementById('date-range-preset');"
        f"sel.value = '{key}';"
        f"sel.dispatchEvent(new Event('change', {{bubbles:true}}));"
    )


def _preset_option_labels(driver):
    """Return non-empty option labels from #date-range-preset."""
    return driver.execute_script(
        "return Array.from(document.querySelectorAll('#date-range-preset option'))"
        ".filter(o => o.value)"
        ".map(o => o.textContent.trim());"
    )


def _assert_nav_basics(driver):
    """Assert the date range nav is present with a functioning select and arrow buttons."""
    assert driver.find_element(By.CSS_SELECTOR, ".date-range-nav") is not None
    assert driver.find_element(By.ID, "date-range-preset") is not None
    assert driver.find_element(By.ID, "date-range-from") is not None
    assert driver.find_element(By.ID, "date-range-to") is not None
    assert driver.find_element(By.ID, "date-range-prev") is not None
    assert driver.find_element(By.ID, "date-range-next") is not None

    labels = _preset_option_labels(driver)
    assert len(labels) >= 6
    assert all(labels), f"Some preset options have no label: {labels}"


# ---------------------------------------------------------------------------
# Expenses list
# ---------------------------------------------------------------------------

class TestDateRangeNavExpenses:
    """Date range nav renders and works on the expenses list page."""

    def test_nav_renders(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _assert_nav_basics(driver)

    def test_preset_select_has_labeled_options(self, driver, w, ctx):
        labels = _preset_option_labels(driver)
        assert len(labels) >= 6
        assert all(labels)

    def test_date_inputs_exist(self, driver, w, ctx):
        assert driver.find_element(By.ID, "date-range-from") is not None
        assert driver.find_element(By.ID, "date-range-to") is not None

    def test_arrow_buttons_exist(self, driver, w, ctx):
        assert driver.find_element(By.ID, "date-range-prev") is not None
        assert driver.find_element(By.ID, "date-range-next") is not None

    def test_preset_select_updates_url(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _select_preset(driver, "cur_year")
        time.sleep(1)
        assert "date_from=" in driver.current_url
        assert "date_to=" in driver.current_url

    def test_preset_enables_arrow_buttons(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _select_preset(driver, "cur_fin_month")
        time.sleep(1)
        prev_disabled = driver.execute_script(
            "return document.getElementById('date-range-prev').disabled;"
        )
        next_disabled = driver.execute_script(
            "return document.getElementById('date-range-next').disabled;"
        )
        assert not prev_disabled
        assert not next_disabled

    def test_arrow_prev_navigates(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _select_preset(driver, "cur_fin_month")
        time.sleep(1)
        from_before = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        driver.find_element(By.ID, "date-range-prev").click()
        time.sleep(1)
        from_after = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        assert from_after < from_before

    def test_arrow_next_navigates(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _select_preset(driver, "cur_fin_month")
        time.sleep(1)
        from_before = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        driver.find_element(By.ID, "date-range-next").click()
        time.sleep(1)
        from_after = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        assert from_after > from_before

    def test_arrow_keeps_working_in_custom_territory(self, driver, w, ctx):
        """Mode persists after navigating past known presets; arrows stay enabled."""
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _select_preset(driver, "cur_fin_month")
        time.sleep(1)
        for _ in range(3):
            driver.find_element(By.ID, "date-range-prev").click()
            time.sleep(0.5)
        # Dropdown shows Custom but arrows must still be enabled
        select_val = driver.execute_script(
            "return document.getElementById('date-range-preset').value;"
        )
        assert select_val == ""  # custom
        prev_disabled = driver.execute_script(
            "return document.getElementById('date-range-prev').disabled;"
        )
        assert not prev_disabled

    def test_arrow_mode_survives_page_reload(self, driver, w, ctx):
        """After navigating into custom territory, a reload must keep arrows enabled."""
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _select_preset(driver, "cur_fin_month")
        time.sleep(1)
        for _ in range(3):
            driver.find_element(By.ID, "date-range-prev").click()
            time.sleep(0.5)
        # Reload the page
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        prev_disabled = driver.execute_script(
            "return document.getElementById('date-range-prev').disabled;"
        )
        assert not prev_disabled

    def test_manual_date_input_updates_url(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        driver.execute_script(
            "var el = document.getElementById('date-range-from');"
            "el.value = '2025-01-01';"
            "el.dispatchEvent(new Event('change', {bubbles:true}));"
        )
        driver.execute_script(
            "var el = document.getElementById('date-range-to');"
            "el.value = '2025-01-31';"
            "el.dispatchEvent(new Event('change', {bubbles:true}));"
        )
        time.sleep(1)
        assert "date_from=2025-01-01" in driver.current_url
        assert "date_to=2025-01-31" in driver.current_url

    def test_manual_input_disables_arrows(self, driver, w, ctx):
        """Manual date edit clears the mode; arrows must disable."""
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _select_preset(driver, "cur_fin_month")
        time.sleep(1)
        driver.execute_script(
            "var el = document.getElementById('date-range-from');"
            "el.value = '2025-03-01';"
            "el.dispatchEvent(new Event('change', {bubbles:true}));"
        )
        driver.execute_script(
            "var el = document.getElementById('date-range-to');"
            "el.value = '2025-03-31';"
            "el.dispatchEvent(new Event('change', {bubbles:true}));"
        )
        time.sleep(1)
        prev_disabled = driver.execute_script(
            "return document.getElementById('date-range-prev').disabled;"
        )
        assert prev_disabled

    def test_clear_button_resets_to_default(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        driver.execute_script(
            "var el = document.getElementById('date-range-from');"
            "el.value = '2020-01-01';"
            "el.dispatchEvent(new Event('change', {bubbles:true}));"
        )
        driver.execute_script(
            "var el = document.getElementById('date-range-to');"
            "el.value = '2020-01-31';"
            "el.dispatchEvent(new Event('change', {bubbles:true}));"
        )
        time.sleep(1)
        driver.find_element(By.ID, "date-range-clear").click()
        time.sleep(1)
        from_val = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        assert from_val != "2020-01-01"

    def test_localStorage_persists_range(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _select_preset(driver, "cur_year")
        time.sleep(1)
        from_val = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        from_val2 = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        assert from_val2 == from_val

    def test_url_param_overrides_localStorage(self, driver, w, ctx):
        driver.execute_script(
            "localStorage.setItem('comaney_date_range',"
            " JSON.stringify({from:'2023-01-01',to:'2023-12-31'}));"
        )
        driver.get(_url("/budget/expenses/?date_from=2025-06-01&date_to=2025-06-30"))
        time.sleep(2)
        from_val = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        assert from_val == "2025-06-01"

    def test_export_link_has_date_params(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        export = driver.find_element(By.CSS_SELECTOR, ".expenses-export-link")
        href = export.get_attribute("href")
        assert "date_from=" in href
        assert "date_to=" in href


# ---------------------------------------------------------------------------
# Expenses filtering
# ---------------------------------------------------------------------------

class TestDateRangeFiltering:
    """Expenses outside the date range are excluded from the list."""

    def test_expense_in_range_is_visible(self, driver, w, ctx):
        today = server_today()
        driver.get(_url(f"/budget/expenses/?date_from={today}&date_to={today}"))
        time.sleep(2)
        assert "DateRange Today Exp" in driver.page_source

    def test_expense_outside_range_is_hidden(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/?date_from=2000-01-01&date_to=2000-01-31"))
        time.sleep(2)
        assert "DateRange Today Exp" not in driver.page_source


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class TestDateRangeNavDashboard:
    """Date range nav renders and works on the dashboard."""

    def test_nav_renders(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/"))
        time.sleep(2)
        _assert_nav_basics(driver)

    def test_preset_select_updates_url(self, driver, w, ctx):
        _select_preset(driver, "cur_year")
        time.sleep(1)
        assert "date_from=" in driver.current_url

    def test_arrow_prev_navigates(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/"))
        time.sleep(2)
        _select_preset(driver, "cur_fin_month")
        time.sleep(1)
        from_before = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        driver.find_element(By.ID, "date-range-prev").click()
        time.sleep(1)
        from_after = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        assert from_after < from_before

    def test_arrow_keeps_working_in_custom_territory(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/budget/"))
        time.sleep(2)
        _select_preset(driver, "cur_year")
        time.sleep(1)
        for _ in range(3):
            driver.find_element(By.ID, "date-range-prev").click()
            time.sleep(0.5)
        select_val = driver.execute_script(
            "return document.getElementById('date-range-preset').value;"
        )
        assert select_val == ""
        prev_disabled = driver.execute_script(
            "return document.getElementById('date-range-prev').disabled;"
        )
        assert not prev_disabled


# ---------------------------------------------------------------------------
# Buddy summary
# ---------------------------------------------------------------------------

class TestDateRangeNavBuddySummary:
    """Date range nav renders and works on the buddy summary page."""

    def test_nav_renders(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        _assert_nav_basics(driver)

    def test_preset_select_updates_url(self, driver, w, ctx):
        _select_preset(driver, "cur_year")
        time.sleep(1)
        assert "date_from=" in driver.current_url

    def test_arrow_prev_navigates(self, driver, w, ctx):
        driver.execute_script("localStorage.clear();")
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        _select_preset(driver, "cur_fin_month")
        time.sleep(1)
        from_before = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        driver.find_element(By.ID, "date-range-prev").click()
        time.sleep(1)
        from_after = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        assert from_after < from_before


# ---------------------------------------------------------------------------
# Project detail
# ---------------------------------------------------------------------------

class TestDateRangeNavAbsentOnProject:
    """Projects always show all-time expenses, so the date-range nav must not render."""

    def test_nav_not_rendered(self, driver, w, ctx, project_url):
        driver.execute_script("localStorage.clear();")
        driver.get(project_url)
        time.sleep(2)
        assert not driver.find_elements(By.ID, "date-range-nav")
        assert not driver.find_elements(By.ID, "date-range-preset")


# ---------------------------------------------------------------------------
# Project pages always show all-time expenses (no date-range filtering)
# ---------------------------------------------------------------------------

# 14 test expenses spread across 2020-2026, two per year.
_PROJECT_FILTER_EXPENSES = [
    {"title": "DR Proj 2020-01-10", "date": "2020-01-10"},
    {"title": "DR Proj 2020-06-15", "date": "2020-06-15"},
    {"title": "DR Proj 2021-03-20", "date": "2021-03-20"},
    {"title": "DR Proj 2021-09-05", "date": "2021-09-05"},
    {"title": "DR Proj 2022-01-15", "date": "2022-01-15"},
    {"title": "DR Proj 2022-07-22", "date": "2022-07-22"},
    {"title": "DR Proj 2023-04-08", "date": "2023-04-08"},
    {"title": "DR Proj 2023-11-30", "date": "2023-11-30"},
    {"title": "DR Proj 2024-02-14", "date": "2024-02-14"},
    {"title": "DR Proj 2024-08-19", "date": "2024-08-19"},
    {"title": "DR Proj 2025-01-01", "date": "2025-01-01"},
    {"title": "DR Proj 2025-06-10", "date": "2025-06-10"},
    {"title": "DR Proj 2026-01-05", "date": "2026-01-05"},
    {"title": "DR Proj 2026-03-15", "date": "2026-03-15"},
]
_ALL_PROJECT_TITLES = [e["title"] for e in _PROJECT_FILTER_EXPENSES]


def _create_project_expenses(feuser_email: str, project_uid: str, expenses: list) -> None:
    """Populate a project with test expenses via Django shell in the Docker container."""
    lines = [
        "from budget.expense_factory import create_expense;",
        "from feusers.models import FeUser;",
        "from buddies.models import BuddyGroup;",
        "from decimal import Decimal;",
        "from datetime import date;",
        f"u = FeUser.objects.get(email='{feuser_email}');",
        f"p = BuddyGroup.objects.get(uid='{project_uid}');",
    ]
    for exp in expenses:
        lines.append(
            f"create_expense(owning_feuser=u, title='{exp['title']}',"
            f" type='expense', value=Decimal('5'),"
            f" date_due=date.fromisoformat('{exp['date']}'),"
            f" settled=True, buddy_approved=True, project=p);"
        )
    lines.append("print('ok')")
    code = " ".join(lines)
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"create_project_expenses failed:\n{result.stderr}"


def _project_uid_from_url(url: str) -> str:
    """Extract the project UID from a project detail URL like /projects/<uid>/."""
    return url.rstrip("/").rsplit("/", 1)[-1]


def _assert_project_shows_all(driver, project_url: str, expect_titles: list,
                               date_from: str = None, date_to: str = None) -> None:
    """
    Navigate to the project (optionally with date_from/date_to URL params), wait
    for the DOMContentLoaded fetchList XHR to replace the server-rendered content,
    then assert that every title in expect_titles appears. Projects have no
    date-range filter, so even narrow/out-of-range date params must not hide
    anything.
    """
    driver.execute_script("localStorage.clear();")
    url = project_url
    if date_from is not None and date_to is not None:
        url = f"{project_url}?date_from={date_from}&date_to={date_to}"
    driver.get(url)
    time.sleep(3)  # allow fetchList XHR to complete

    src = driver.page_source
    missing = [title for title in expect_titles if title not in src]
    assert not missing, "Expected all-time expenses, missing:\n" + "\n".join(missing)


@pytest.fixture(scope="module")
def project_filter_url(driver, w, ctx):
    """
    Create a dedicated project for filtering tests and populate it with
    14 known expenses spread across 2020-2026.  Returns the project URL.
    """
    driver.execute_script("localStorage.clear();")
    driver.get(_url("/projects/"))
    time.sleep(2)
    driver.execute_script(
        "document.getElementById('project-name').value = 'DR Filter Project';"
    )
    driver.find_element(By.ID, "btn-create-project").click()
    time.sleep(2)
    url = driver.current_url

    project_uid = _project_uid_from_url(url)
    _create_project_expenses(ctx["email"], project_uid, _PROJECT_FILTER_EXPENSES)
    yield url


class TestProjectAlwaysShowsAllTime:
    """
    Projects have no date-range picker: the expense list always shows the
    project's entire history, regardless of any date_from/date_to URL params.
    """

    def test_no_params_shows_all_expenses(self, driver, w, ctx, project_filter_url):
        """With no date params at all, every one of the 14 test expenses appears."""
        _assert_project_shows_all(driver, project_filter_url, _ALL_PROJECT_TITLES)

    def test_single_day_range_is_ignored(self, driver, w, ctx, project_filter_url):
        """A single-day range that would normally match only one expense must
        still show all 14: date params have no effect on projects."""
        _assert_project_shows_all(
            driver, project_filter_url, _ALL_PROJECT_TITLES,
            date_from="2022-01-15", date_to="2022-01-15",
        )

    def test_range_before_all_data_is_ignored(self, driver, w, ctx, project_filter_url):
        """A range entirely before 2020 must still show every expense."""
        _assert_project_shows_all(
            driver, project_filter_url, _ALL_PROJECT_TITLES,
            date_from="2019-01-01", date_to="2019-12-31",
        )

    def test_manual_date_inputs_have_no_effect(self, driver, w, ctx, project_filter_url):
        """Even if date inputs existed elsewhere on the page and changed the
        global date range, the project's fetchList ignores it and a manual
        URL date param round-trip still shows everything."""
        _assert_project_shows_all(
            driver, project_filter_url, _ALL_PROJECT_TITLES,
            date_from="2021-01-01", date_to="2021-12-31",
        )


# ---------------------------------------------------------------------------
# Edge cases: no due date fallback and pending expense filtering
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def project_edge_url(driver, w, ctx):
    """
    A project with three edge-case expenses:
      - one expense with no due date (falls back to date_created)
      - one pending expense (buddy_approved=False) with a known due date
      - one approved expense with the same known due date
    Returns the project URL.
    """
    driver.execute_script("localStorage.clear();")
    driver.get(_url("/projects/"))
    time.sleep(2)
    driver.execute_script(
        "document.getElementById('project-name').value = 'DR Edge Project';"
    )
    driver.find_element(By.ID, "btn-create-project").click()
    time.sleep(2)
    url = driver.current_url
    project_uid = _project_uid_from_url(url)

    pending_due = "2023-03-15"

    code = (
        "from budget.expense_factory import create_expense;"
        "from feusers.models import FeUser;"
        "from buddies.models import BuddyGroup;"
        "from decimal import Decimal;"
        f"u = FeUser.objects.get(email='{ctx['email']}');"
        f"p = BuddyGroup.objects.get(uid='{project_uid}');"
        # No due date: falls back to date_created (= today on the server)
        "create_expense(owning_feuser=u, title='DR Edge No Due Date',"
        " type='expense', value=Decimal('5'),"
        " date_due=None, settled=True, buddy_approved=True, project=p);"
        # Pending expense: buddy_approved=False, due date in 2023
        "create_expense(owning_feuser=u, title='DR Edge Pending 2023',"
        " type='expense', value=Decimal('5'),"
        f" date_due=__import__('datetime').date.fromisoformat('{pending_due}'),"
        " settled=False, buddy_approved=False, project=p);"
        # Approved expense with the same 2023 date
        "create_expense(owning_feuser=u, title='DR Edge Approved 2023',"
        " type='expense', value=Decimal('5'),"
        f" date_due=__import__('datetime').date.fromisoformat('{pending_due}'),"
        " settled=True, buddy_approved=True, project=p);"
        "print('ok')"
    )
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"project_edge_url setup failed:\n{result.stderr}"

    yield url


class TestProjectEdgeCasesAlwaysVisible:
    """
    No-due-date and pending (buddy_approved=False) expenses are ordinary
    project expenses now that projects always show all-time data: they must
    remain visible no matter what date params are passed.
    """

    _ALL_EDGE_TITLES = [
        "DR Edge No Due Date",
        "DR Edge Pending 2023",
        "DR Edge Approved 2023",
    ]

    def test_all_visible_without_date_params(self, driver, w, ctx, project_edge_url):
        _assert_project_shows_all(driver, project_edge_url, self._ALL_EDGE_TITLES)

    def test_all_visible_despite_unrelated_date_params(self, driver, w, ctx, project_edge_url):
        """A date range covering none of the expenses' real dates must still
        show all of them, since date params have no effect on projects."""
        _assert_project_shows_all(
            driver, project_edge_url, self._ALL_EDGE_TITLES,
            date_from="2020-01-01", date_to="2020-12-31",
        )
