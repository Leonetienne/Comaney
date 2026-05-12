"""Month/year period toggle on dashboard and expenses list."""
from datetime import date

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import _url, wait_text, setup_user, cleanup_user

CURRENT_YEAR = str(date.today().year)
PREV_YEAR    = str(date.today().year - 1)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestPeriodDashboard:

    def test_year_view_loads(self, driver, w, ctx):
        driver.get(_url(f"/budget/?view=year&year={CURRENT_YEAR}"))
        wait_text(driver, w, CURRENT_YEAR)
        assert "period-toggle__opt active" in driver.page_source

    def test_year_prev_arrow(self, driver, w, ctx):
        arrow = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, ".month-nav__arrow[aria-label='Previous year']")))
        arrow.click()
        wait_text(driver, w, PREV_YEAR)
        assert f"view=year&year={PREV_YEAR}" in driver.current_url

    def test_year_next_arrow(self, driver, w, ctx):
        arrow = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, ".month-nav__arrow[aria-label='Next year']")))
        arrow.click()
        wait_text(driver, w, CURRENT_YEAR)
        assert f"view=year&year={CURRENT_YEAR}" in driver.current_url

    def test_switch_to_months(self, driver, w, ctx):
        months_link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(@class,'period-toggle__opt') and text()='Months']")))
        months_link.click()
        w.until(lambda d: "view=year" not in d.current_url)
        month_names = ["January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]
        assert any(m in driver.page_source for m in month_names)

    def test_switch_back_to_years(self, driver, w, ctx):
        years_link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(@class,'period-toggle__opt') and text()='Years']")))
        years_link.click()
        w.until(lambda d: "view=year" in d.current_url)
        wait_text(driver, w, CURRENT_YEAR)


class TestPeriodExpenses:

    def test_year_view_loads(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/?view=year&year={CURRENT_YEAR}"))
        wait_text(driver, w, CURRENT_YEAR)
        assert "period-toggle__opt active" in driver.page_source

    def test_year_export_link(self, driver, w, ctx):
        export = w.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".expenses-export-link")))
        href = export.get_attribute("href")
        assert "view=year" in href
        assert CURRENT_YEAR in href

    def test_month_export_link(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        export = w.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".expenses-export-link")))
        href = export.get_attribute("href")
        assert "view=year" not in href
        assert "month=" in href
