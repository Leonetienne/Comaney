"""
Expense list controls: live search, select-all/deselect, visible total,
and bulk settle/unsettle/delete actions.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select as SeleniumSelect
from selenium.webdriver.support.ui import WebDriverWait

from helpers import (
    _url, click, wait_text, server_today,
    api_get, api_post, api_delete, CLICK_PACE,
    setup_user, cleanup_user,
)

# Titles scoped with a prefix so they are easy to isolate via the search box.
PREFIX   = "BulkTest"
TITLE_A  = f"{PREFIX} Alpha"
TITLE_B  = f"{PREFIX} Beta"
TITLE_C  = f"{PREFIX} Gamma Income"


def _wait_search_idle(driver, timeout=4.0):
    WebDriverWait(driver, timeout).until(
        lambda d: (
            not d.find_element(By.ID, "exp-list").get_attribute("data-search-pending") and
            not d.find_element(By.ID, "exp-list").get_attribute("data-search-loading")
        )
    )


def search_type(driver, value):
    el = driver.find_element(By.ID, "exp-search")
    driver.execute_script(
        "arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
        el, value,
    )
    _wait_search_idle(driver)
    time.sleep(1)


def search_clear(driver):
    search_type(driver, "")


def visible_cards(driver):
    return [c for c in driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card")
            if c.value_of_css_property("display") != "none"]


def visible_titles(driver):
    return [c.find_element(By.CSS_SELECTOR, ".exp-title").text for c in visible_cards(driver)]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestBulkSetup:

    def test_create_expenses(self, driver, w, ctx):
        today = server_today()
        a = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_A, "type": "expense", "value": "100.00",
            "date_due": today, "settled": False,
        })
        b = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_B, "type": "expense", "value": "200.00",
            "date_due": today, "settled": False,
        })
        c_exp = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_C, "type": "income", "value": "300.00",
            "date_due": today, "settled": False,
        })
        assert a.status_code == 201
        assert b.status_code == 201
        assert c_exp.status_code == 201
        ctx["uid_a"] = a.json()["id"]
        ctx["uid_b"] = b.json()["id"]
        ctx["uid_c"] = c_exp.json()["id"]


class TestSearch:

    def test_filters_cards(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, TITLE_A)
        titles = visible_titles(driver)
        assert any(TITLE_A in t for t in titles)
        assert not any(TITLE_B in t for t in titles)
        assert not any(TITLE_C in t for t in titles)

    def test_clear_restores_all(self, driver, w, ctx):
        search_clear(driver)
        titles = visible_titles(driver)
        assert any(TITLE_A in t for t in titles)
        assert any(TITLE_B in t for t in titles)
        assert any(TITLE_C in t for t in titles)


class TestSelectAll:

    def test_select_all_checks_visible(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, PREFIX)
        click(w, By.ID, "exp-select-all")
        for card in visible_cards(driver):
            assert card.find_element(By.CSS_SELECTOR, ".exp-checkbox").is_selected()
        assert driver.find_element(By.ID, "exp-select-all").text.strip().lower() == "deselect all"

    def test_deselect_all(self, driver, w, ctx):
        click(w, By.ID, "exp-select-all")
        for card in visible_cards(driver):
            assert not card.find_element(By.CSS_SELECTOR, ".exp-checkbox").is_selected()
        search_clear(driver)

    def test_scoped_to_search(self, driver, w, ctx):
        """Select all only checks the cards visible under the active search filter."""
        search_type(driver, TITLE_A)
        click(w, By.ID, "exp-select-all")
        for card in driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card"):
            cb    = card.find_element(By.CSS_SELECTOR, ".exp-checkbox")
            title = card.find_element(By.CSS_SELECTOR, ".exp-title").text
            if TITLE_A in title:
                assert cb.is_selected()
            elif card.value_of_css_property("display") != "none":
                assert not cb.is_selected()
        search_clear(driver)
        click(w, By.ID, "exp-select-all")  # deselect


class TestVisibleTotal:

    def test_total_income_minus_expenses(self, driver, w, ctx):
        """Visible total: income 300 - expense 100 - expense 200 = 0."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, PREFIX)
        raw = driver.find_element(By.ID, "exp-sum-value").text.strip()
        assert raw != "-", "Sum should be calculated"
        assert abs(float(raw)) < 0.01, f"Expected 0.00, got {raw}"

    def test_total_updates_on_search(self, driver, w, ctx):
        search_type(driver, TITLE_A)
        raw = driver.find_element(By.ID, "exp-sum-value").text.strip()
        assert abs(float(raw) - (-100.0)) < 0.01, f"Expected -100.00, got {raw}"
        search_clear(driver)


def _select_prefix(driver, w):
    search_type(driver, PREFIX)
    click(w, By.ID, "exp-select-all")


def _bulk_action(driver, w, action_value):
    SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value(action_value)
    driver.find_element(By.ID, "exp-bulk-go").click()
    time.sleep(CLICK_PACE)
    w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
    time.sleep(CLICK_PACE)
    w.until(lambda d: d.execute_script("return document.readyState") == "complete")
    wait_text(driver, w, "Expenses")


class TestBulkActions:

    def test_bulk_settle(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        _select_prefix(driver, w)
        _bulk_action(driver, w, "settle")
        for key in ("uid_a", "uid_b", "uid_c"):
            assert api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["settled"] is True

    def test_bulk_unsettle(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        _select_prefix(driver, w)
        _bulk_action(driver, w, "unsettle")
        for key in ("uid_a", "uid_b", "uid_c"):
            assert api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["settled"] is False

    def test_bulk_action_scoped_to_filter(self, driver, w, ctx):
        """Settling only Alpha via filtered bulk action must not touch Beta."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, TITLE_A)
        click(w, By.ID, "exp-select-all")
        _bulk_action(driver, w, "settle")
        assert api_get(f"/api/v1/expenses/{ctx['uid_a']}/", ctx).json()["settled"] is True
        assert api_get(f"/api/v1/expenses/{ctx['uid_b']}/", ctx).json()["settled"] is False
        # restore
        driver.get(_url("/budget/expenses/"))
        _select_prefix(driver, w)
        _bulk_action(driver, w, "unsettle")

    def test_bulk_delete_cancel_keeps_expenses(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, PREFIX)
        click(w, By.ID, "exp-select-all")
        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value("delete")
        driver.find_element(By.ID, "exp-bulk-go").click()
        time.sleep(CLICK_PACE)
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-cancel"))).click()
        time.sleep(CLICK_PACE)
        assert TITLE_A in driver.page_source

    def test_bulk_delete(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        anchor = driver.find_element(By.ID, "exp-list")
        _select_prefix(driver, w)
        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value("delete")
        driver.find_element(By.ID, "exp-bulk-go").click()
        time.sleep(CLICK_PACE)
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        w.until(EC.staleness_of(anchor))
        w.until(lambda d: TITLE_A not in d.page_source)
        for key in ("uid_a", "uid_b", "uid_c"):
            ctx.pop(key, None)
