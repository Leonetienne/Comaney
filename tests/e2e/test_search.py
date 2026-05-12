"""
Expense search and query parser.

Covers: tag=, cat=, payee= filters; type= filter; date comparisons; NOT operator;
OR operator; sessionStorage persistence across navigation.

All expenses use a unique keyword "SrchTest" so other data never interferes.
Date-comparison tests pin expenses to a fixed reference year (2025) and
always query with view=year&year=2025 to avoid month-boundary clipping.
"""
import time
from datetime import date

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from helpers import (
    _url, api_get, api_post, api_patch, api_delete, server_today,
    setup_user, cleanup_user,
)

FIXED_YEAR = 2025
DATE_EARLY  = "2025-02-01"
DATE_MID    = "2025-06-15"
DATE_LATE   = "2025-11-01"


def _wait_idle(driver, timeout=4.0):
    WebDriverWait(driver, timeout).until(
        lambda d: (
            not d.find_element(By.ID, "exp-list").get_attribute("data-search-pending") and
            not d.find_element(By.ID, "exp-list").get_attribute("data-search-loading")
        )
    )


def _search(driver, query):
    el = driver.find_element(By.ID, "exp-search")
    driver.execute_script(
        "arguments[0].value=arguments[1];"
        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
        el, query,
    )
    _wait_idle(driver)
    time.sleep(1)


def _visible_titles(driver):
    return [
        c.find_element(By.CSS_SELECTOR, ".exp-title").text
        for c in driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card")
        if c.value_of_css_property("display") != "none"
    ]


def _expenses_url(year=FIXED_YEAR):
    return _url(f"/budget/expenses/?view=year&year={year}")


def _api_titles(ctx, q, year=FIXED_YEAR):
    resp = api_get("/api/v1/expenses/", ctx,
                   params={"q": q, "year": year, "view": "year"})
    assert resp.status_code == 200
    return [e["title"] for e in resp.json()["expenses"]]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module", autouse=True)
def setup_data(ctx, driver, w):
    """Create all test expenses, category, and tags. Clean up after module."""
    cat_r = api_post("/api/v1/categories/", ctx, json={"title": "SrchTestCat"})
    assert cat_r.status_code == 201
    cat_id = cat_r.json()["id"]

    tag_r = api_post("/api/v1/tags/", ctx, json={"title": "SrchTestTag"})
    assert tag_r.status_code == 201
    tag_id = tag_r.json()["id"]

    expenses = [
        {"title": "SrchTest Alpha",   "type": "expense", "value": "100.00",
         "date_due": DATE_EARLY, "settled": False,
         "payee": "Vendor Alpha", "category_id": cat_id, "tag_ids": [tag_id]},
        {"title": "SrchTest Beta",    "type": "expense", "value": "200.00",
         "date_due": DATE_MID,   "settled": True,  "payee": "Vendor Beta"},
        {"title": "SrchTest Gamma",   "type": "income",  "value": "300.00",
         "date_due": DATE_LATE,  "settled": True},
        {"title": "SrchTest Deact",   "type": "expense", "value": "50.00",
         "date_due": DATE_MID,   "settled": False, "deactivated": True},
    ]
    eids = []
    for body in expenses:
        r = api_post("/api/v1/expenses/", ctx, json=body)
        assert r.status_code == 201, r.text
        eids.append(r.json()["id"])

    ctx["srch_cat_id"] = cat_id
    ctx["srch_tag_id"] = tag_id
    ctx["srch_eids"]   = eids

    yield

    for eid in ctx.get("srch_eids", []):
        api_delete(f"/api/v1/expenses/{eid}/", ctx)
    if "srch_cat_id" in ctx:
        api_delete(f"/api/v1/categories/{ctx['srch_cat_id']}/", ctx)
    if "srch_tag_id" in ctx:
        api_delete(f"/api/v1/tags/{ctx['srch_tag_id']}/", ctx)


class TestFilterByAttributes:

    def test_tag_filter(self, driver, w, ctx):
        titles = _api_titles(ctx, "tag=SrchTestTag")
        assert "SrchTest Alpha" in titles
        assert "SrchTest Beta" not in titles

    def test_cat_filter(self, driver, w, ctx):
        titles = _api_titles(ctx, "cat=SrchTestCat")
        assert "SrchTest Alpha" in titles
        assert "SrchTest Beta" not in titles

    def test_payee_filter(self, driver, w, ctx):
        titles = _api_titles(ctx, "payee=Vendor Alpha")
        assert "SrchTest Alpha" in titles
        assert "SrchTest Beta" not in titles

    def test_type_filter_income(self, driver, w, ctx):
        titles = _api_titles(ctx, "type=income")
        assert "SrchTest Gamma" in titles
        assert "SrchTest Alpha" not in titles

    def test_settled_filter(self, driver, w, ctx):
        titles = _api_titles(ctx, "settled=yes")
        assert "SrchTest Beta" in titles
        assert "SrchTest Alpha" not in titles

    def test_deactivated_filter(self, driver, w, ctx):
        titles = _api_titles(ctx, "deactivated=yes")
        assert "SrchTest Deact" in titles
        assert "SrchTest Alpha" not in titles


class TestDateComparisons:

    def test_date_equal(self, driver, w, ctx):
        titles = _api_titles(ctx, f"date={DATE_MID}")
        assert "SrchTest Beta" in titles
        assert "SrchTest Alpha" not in titles

    def test_date_greater_than(self, driver, w, ctx):
        titles = _api_titles(ctx, f"date>{DATE_MID}")
        assert "SrchTest Gamma" in titles
        assert "SrchTest Alpha" not in titles
        assert "SrchTest Beta" not in titles

    def test_date_less_than(self, driver, w, ctx):
        titles = _api_titles(ctx, f"date<{DATE_MID}")
        assert "SrchTest Alpha" in titles
        assert "SrchTest Gamma" not in titles

    def test_date_gte(self, driver, w, ctx):
        titles = _api_titles(ctx, f"date>={DATE_MID}")
        assert "SrchTest Beta" in titles
        assert "SrchTest Gamma" in titles
        assert "SrchTest Alpha" not in titles


class TestLogicalOperators:

    def test_not_operator(self, driver, w, ctx):
        titles = _api_titles(ctx, "SrchTest !Beta")
        assert "SrchTest Alpha" in titles
        assert "SrchTest Beta" not in titles

    def test_or_operator(self, driver, w, ctx):
        titles = _api_titles(ctx, "SrchTest Alpha || SrchTest Gamma")
        assert "SrchTest Alpha" in titles
        assert "SrchTest Gamma" in titles
        assert "SrchTest Beta" not in titles


class TestBrowserSearch:

    def test_live_search_filters_cards(self, driver, w, ctx):
        driver.get(_expenses_url())
        _wait_idle(driver)
        _search(driver, "SrchTest Alpha")
        titles = _visible_titles(driver)
        assert any("SrchTest Alpha" in t for t in titles)
        assert not any("SrchTest Beta" in t for t in titles)

    def test_session_storage_restores(self, driver, w, ctx):
        """Navigating to an expense edit page and back restores the search from sessionStorage."""
        expenses_url = _url("/budget/expenses/")
        driver.get(expenses_url)
        _wait_idle(driver)
        _search(driver, "SrchTest")
        eid = ctx["srch_eids"][0]
        # Use JS navigation so document.referrer is preserved (driver.get() clears it).
        driver.execute_script(f"window.location.href = '{_url(f'/budget/expenses/{eid}/edit/')}'")
        time.sleep(1)
        driver.execute_script(f"window.location.href = '{expenses_url}'")
        time.sleep(2)
        _wait_idle(driver)

        current_value = driver.execute_script(
            "return document.getElementById('exp-search').value")
        assert current_value == "SrchTest", (
            f"Expected search restored from sessionStorage, got: '{current_value}'")
        _search(driver, "")
