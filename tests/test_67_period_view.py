"""Tests: MONTHS / YEARS period toggle on dashboard and expenses list."""
from datetime import date

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from conftest import BASE_URL, _url, wait_text


CURRENT_YEAR = str(date.today().year)
PREV_YEAR    = str(date.today().year - 1)

DASHBOARD_URL = "/budget/"
EXPENSES_URL  = "/budget/expenses/"


class TestPeriodView:

    # ── Dashboard year view ──────────────────────────────────────────────────

    def test_01_dashboard_year_view_loads(self, driver, w, ctx):
        driver.get(_url(f"{DASHBOARD_URL}?view=year&year={CURRENT_YEAR}"))
        wait_text(driver, w, CURRENT_YEAR)
        assert 'period-toggle__opt active' in driver.page_source

    def test_02_dashboard_year_label_shown(self, driver, w, ctx):
        """Year label (e.g. '2026') appears in the nav, not a month name."""
        src = driver.page_source
        assert CURRENT_YEAR in src
        assert 'month-nav__label' in src

    def test_03_dashboard_year_prev_arrow(self, driver, w, ctx):
        """Clicking the previous-year arrow loads the previous year."""
        arrow = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, ".month-nav__arrow[aria-label='Previous year']")))
        arrow.click()
        wait_text(driver, w, PREV_YEAR)
        assert f"view=year&year={PREV_YEAR}" in driver.current_url

    def test_04_dashboard_year_next_arrow(self, driver, w, ctx):
        """Next-year arrow returns to current year."""
        arrow = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, ".month-nav__arrow[aria-label='Next year']")))
        arrow.click()
        wait_text(driver, w, CURRENT_YEAR)
        assert f"view=year&year={CURRENT_YEAR}" in driver.current_url

    def test_05_dashboard_switch_to_months(self, driver, w, ctx):
        """Clicking 'Months' toggle switches back to month view."""
        months_link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(@class,'period-toggle__opt') and text()='Months']")))
        months_link.click()
        w.until(lambda d: "view=year" not in d.current_url)
        src = driver.page_source
        assert any(m in src for m in [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ])

    def test_06_dashboard_switch_back_to_years(self, driver, w, ctx):
        """Clicking 'Years' toggle from month view enters year view."""
        years_link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(@class,'period-toggle__opt') and text()='Years']")))
        years_link.click()
        w.until(lambda d: "view=year" in d.current_url)
        wait_text(driver, w, CURRENT_YEAR)

    # ── Expenses list year view ──────────────────────────────────────────────

    def test_07_expenses_year_view_loads(self, driver, w, ctx):
        driver.get(_url(f"{EXPENSES_URL}?view=year&year={CURRENT_YEAR}"))
        wait_text(driver, w, CURRENT_YEAR)
        assert 'period-toggle__opt active' in driver.page_source

    def test_08_expenses_year_prev_arrow(self, driver, w, ctx):
        arrow = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, ".month-nav__arrow[aria-label='Previous year']")))
        arrow.click()
        wait_text(driver, w, PREV_YEAR)
        assert f"view=year&year={PREV_YEAR}" in driver.current_url

    def test_09_expenses_year_export_link(self, driver, w, ctx):
        """Export link in year mode carries view=year param."""
        driver.get(_url(f"{EXPENSES_URL}?view=year&year={CURRENT_YEAR}"))
        export = w.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".expenses-export-link")))
        href = export.get_attribute("href")
        assert "view=year" in href
        assert CURRENT_YEAR in href

    def test_10_expenses_month_export_link(self, driver, w, ctx):
        """Export link in month mode does not carry view=year."""
        driver.get(_url(EXPENSES_URL))
        export = w.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".expenses-export-link")))
        href = export.get_attribute("href")
        assert "view=year" not in href
        assert "month=" in href
