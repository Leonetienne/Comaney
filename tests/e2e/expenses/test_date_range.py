"""Date range selector on expenses list, dashboard, buddy summary, and project detail."""
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

class TestDateRangeNavProject:
    """Date range nav renders and works on a project detail page."""

    def test_nav_renders(self, driver, w, ctx, project_url):
        driver.execute_script("localStorage.clear();")
        driver.get(project_url)
        time.sleep(2)
        _assert_nav_basics(driver)

    def test_preset_select_updates_url(self, driver, w, ctx, project_url):
        driver.execute_script("localStorage.clear();")
        driver.get(project_url)
        time.sleep(2)
        _select_preset(driver, "cur_year")
        time.sleep(1)
        assert "date_from=" in driver.current_url

    def test_arrow_prev_navigates(self, driver, w, ctx, project_url):
        driver.execute_script("localStorage.clear();")
        driver.get(project_url)
        time.sleep(2)
        _select_preset(driver, "cur_fin_month")
        time.sleep(1)
        from_before = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        driver.find_element(By.ID, "date-range-prev").click()
        time.sleep(1)
        from_after = driver.find_element(By.ID, "date-range-from").get_attribute("value")
        assert from_after < from_before


# ---------------------------------------------------------------------------
# Project date-range filtering
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


def _assert_project_filter(driver, project_url: str, date_from: str, date_to: str,
                            expect_visible: list, expect_hidden: list) -> None:
    """
    Navigate to the project with the given date range as URL params, wait for the
    DOMContentLoaded fetchList XHR to replace the server-rendered content, then
    assert that every title in expect_visible appears and every title in
    expect_hidden does not appear.  All mismatches are collected and reported together.
    """
    driver.execute_script("localStorage.clear();")
    driver.get(f"{project_url}?date_from={date_from}&date_to={date_to}")
    time.sleep(3)  # allow fetchList XHR to complete

    src = driver.page_source
    errors = []
    for title in expect_visible:
        if title not in src:
            errors.append(f"MISSING  (should be visible): {title}")
    for title in expect_hidden:
        if title in src:
            errors.append(f"PRESENT  (should be hidden): {title}")
    assert not errors, "Date filter mismatch:\n" + "\n".join(errors)


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


class TestDateRangeFilteringProject:
    """
    Project expense list respects date filtering: in-range expenses appear,
    out-of-range expenses do not.  Both missing and unexpected entries fail the test.
    """

    def test_year_2022_shows_only_2022_expenses(self, driver, w, ctx, project_filter_url):
        """Only the two 2022 expenses appear when filtering to calendar year 2022."""
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2022-01-01", date_to="2022-12-31",
            expect_visible=["DR Proj 2022-01-15", "DR Proj 2022-07-22"],
            expect_hidden=[t for t in _ALL_PROJECT_TITLES
                           if t not in ("DR Proj 2022-01-15", "DR Proj 2022-07-22")],
        )

    def test_range_2023_to_2024_shows_four_expenses(self, driver, w, ctx, project_filter_url):
        """All four 2023-2024 expenses appear; the other ten are absent."""
        in_range = [
            "DR Proj 2023-04-08", "DR Proj 2023-11-30",
            "DR Proj 2024-02-14", "DR Proj 2024-08-19",
        ]
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2023-01-01", date_to="2024-12-31",
            expect_visible=in_range,
            expect_hidden=[t for t in _ALL_PROJECT_TITLES if t not in in_range],
        )

    def test_range_2025_h1_shows_two_expenses(self, driver, w, ctx, project_filter_url):
        """The two H1-2025 expenses appear; all twelve others are absent."""
        in_range = ["DR Proj 2025-01-01", "DR Proj 2025-06-10"]
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2025-01-01", date_to="2025-06-30",
            expect_visible=in_range,
            expect_hidden=[t for t in _ALL_PROJECT_TITLES if t not in in_range],
        )

    def test_range_before_all_data_shows_nothing(self, driver, w, ctx, project_filter_url):
        """A date range entirely before 2020 returns an empty expense list."""
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2019-01-01", date_to="2019-12-31",
            expect_visible=[],
            expect_hidden=_ALL_PROJECT_TITLES,
        )

    def test_single_day_matches_exactly_one_expense(self, driver, w, ctx, project_filter_url):
        """A single-day range matches exactly one expense and hides all others."""
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2024-02-14", date_to="2024-02-14",
            expect_visible=["DR Proj 2024-02-14"],
            expect_hidden=[t for t in _ALL_PROJECT_TITLES if t != "DR Proj 2024-02-14"],
        )

    def test_range_covering_all_shows_all(self, driver, w, ctx, project_filter_url):
        """A wide range covering all test expenses returns every one of them."""
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2019-01-01", date_to="2030-12-31",
            expect_visible=_ALL_PROJECT_TITLES,
            expect_hidden=[],
        )

    def test_dynamic_date_input_filters_list(self, driver, w, ctx, project_filter_url):
        """
        Changing the date range via the date inputs dynamically re-fetches the list.
        Expenses outside the new range disappear; those inside appear.
        """
        driver.execute_script("localStorage.clear();")
        driver.get(project_filter_url)
        time.sleep(3)  # wait for initial fetchList

        # Apply 2021-01-01 to 2021-12-31 via the date inputs
        driver.execute_script(
            "var el = document.getElementById('date-range-from');"
            "el.value = '2021-01-01';"
            "el.dispatchEvent(new Event('change', {bubbles:true}));"
        )
        driver.execute_script(
            "var el = document.getElementById('date-range-to');"
            "el.value = '2021-12-31';"
            "el.dispatchEvent(new Event('change', {bubbles:true}));"
        )
        time.sleep(2)

        in_range = ["DR Proj 2021-03-20", "DR Proj 2021-09-05"]
        src = driver.page_source
        errors = []
        for title in in_range:
            if title not in src:
                errors.append(f"MISSING  (should be visible): {title}")
        for title in _ALL_PROJECT_TITLES:
            if title not in in_range and title in src:
                errors.append(f"PRESENT  (should be hidden): {title}")
        assert not errors, "Dynamic filter mismatch:\n" + "\n".join(errors)

    # -- Boundary tests -------------------------------------------------------

    def test_start_boundary_is_inclusive(self, driver, w, ctx, project_filter_url):
        """An expense whose date_due equals date_from is visible (start is inclusive)."""
        # DR Proj 2022-01-15 is exactly on the start date
        in_range = ["DR Proj 2022-01-15", "DR Proj 2022-07-22"]
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2022-01-15", date_to="2022-12-31",
            expect_visible=in_range,
            expect_hidden=[t for t in _ALL_PROJECT_TITLES if t not in in_range],
        )

    def test_expense_one_day_before_start_is_excluded(self, driver, w, ctx, project_filter_url):
        """An expense whose date_due is one day before date_from is not visible."""
        # DR Proj 2022-01-15 is Jan 15; start is Jan 16 -> must be hidden
        # DR Proj 2022-07-22 is Jul 22; end is Jul 21  -> must be hidden
        # Gap between the two 2022 expenses with neither endpoint included
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2022-01-16", date_to="2022-07-21",
            expect_visible=[],
            expect_hidden=_ALL_PROJECT_TITLES,
        )

    def test_end_boundary_is_inclusive(self, driver, w, ctx, project_filter_url):
        """An expense whose date_due equals date_to is visible (end is inclusive)."""
        # DR Proj 2022-07-22 is exactly on the end date
        in_range = ["DR Proj 2022-01-15", "DR Proj 2022-07-22"]
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2022-01-01", date_to="2022-07-22",
            expect_visible=in_range,
            expect_hidden=[t for t in _ALL_PROJECT_TITLES if t not in in_range],
        )

    def test_expense_one_day_after_end_is_excluded(self, driver, w, ctx, project_filter_url):
        """An expense whose date_due is one day after date_to is not visible."""
        # DR Proj 2022-07-22 is Jul 22; end is Jul 21 -> must be hidden
        in_range = ["DR Proj 2022-01-15"]
        _assert_project_filter(
            driver, project_filter_url,
            date_from="2022-01-01", date_to="2022-07-21",
            expect_visible=in_range,
            expect_hidden=[t for t in _ALL_PROJECT_TITLES if t not in in_range],
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
    Returns {"url": str, "today": str, "pending_due": str}.
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

    today = server_today()
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

    yield {"url": url, "today": today, "pending_due": pending_due}


class TestDateRangeEdgeCases:
    """
    Edge cases for the project date filter:
    expenses with no due date (falls back to date_created) and pending
    expenses (buddy_approved=False) must be filtered exactly the same way
    as ordinary approved expenses.
    """

    _ALL_EDGE_TITLES = [
        "DR Edge No Due Date",
        "DR Edge Pending 2023",
        "DR Edge Approved 2023",
    ]

    def _get(self, info, *keys):
        return tuple(info[k] for k in keys)

    # -- no due date ---------------------------------------------------------

    def test_no_due_date_expense_visible_for_creation_date(
            self, driver, w, ctx, project_edge_url):
        """
        An expense with no due date is matched against date_created.
        A range covering today must show it.
        """
        today = project_edge_url["today"]
        url = project_edge_url["url"]
        _assert_project_filter(
            driver, url,
            date_from=today, date_to=today,
            expect_visible=["DR Edge No Due Date"],
            expect_hidden=["DR Edge Pending 2023", "DR Edge Approved 2023"],
        )

    def test_no_due_date_expense_hidden_outside_creation_date(
            self, driver, w, ctx, project_edge_url):
        """
        A range that does NOT include today must hide the no-due-date expense
        (it falls back to date_created, which is today).
        """
        url = project_edge_url["url"]
        _assert_project_filter(
            driver, url,
            date_from="2020-01-01", date_to="2020-12-31",
            expect_visible=[],
            expect_hidden=self._ALL_EDGE_TITLES,
        )

    # -- pending expense filtering -------------------------------------------

    def test_pending_expense_visible_when_in_range(
            self, driver, w, ctx, project_edge_url):
        """
        A pending (buddy_approved=False) expense whose due date is inside
        the selected range must appear in the list.
        """
        url = project_edge_url["url"]
        due = project_edge_url["pending_due"]
        _assert_project_filter(
            driver, url,
            date_from=due, date_to=due,
            expect_visible=["DR Edge Pending 2023", "DR Edge Approved 2023"],
            expect_hidden=["DR Edge No Due Date"],
        )

    def test_pending_expense_hidden_when_out_of_range(
            self, driver, w, ctx, project_edge_url):
        """
        A pending expense whose due date is outside the selected range
        must NOT appear, just like an approved expense would not.
        """
        url = project_edge_url["url"]
        _assert_project_filter(
            driver, url,
            date_from="2024-01-01", date_to="2024-12-31",
            expect_visible=[],
            expect_hidden=self._ALL_EDGE_TITLES,
        )

    def test_pending_and_approved_filtered_identically(
            self, driver, w, ctx, project_edge_url):
        """
        Both the pending and the approved expense share the same due date.
        A range that includes only that date must show both and hide the
        no-due-date expense.  This confirms both expense types go through
        the same date filter path.
        """
        url = project_edge_url["url"]
        due = project_edge_url["pending_due"]
        # Narrow 1-month window around the 2023-03-15 due date
        _assert_project_filter(
            driver, url,
            date_from="2023-03-01", date_to="2023-03-31",
            expect_visible=["DR Edge Pending 2023", "DR Edge Approved 2023"],
            expect_hidden=["DR Edge No Due Date"],
        )
