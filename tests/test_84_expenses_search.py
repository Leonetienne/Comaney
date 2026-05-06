"""
Expense list – extended search and filter persistence.

Tests:
  - tag:, cat:, payee: prefix filters (with and without quotes)
  - combined prefix + free-text
  - sessionStorage restores search after navigation away and back
"""
from datetime import date

import time
import pytest
from selenium.webdriver.common.by import By

from conftest import _url, click, wait_text, server_today, api_post, api_get, api_delete, CLICK_PACE


TODAY = server_today()

TITLE_ALPHA = "SearchTest Alpha"
TITLE_BETA  = "SearchTest Beta"
PAYEE_ALPHA = "Rainer Winkler"
PAYEE_BETA  = "Hans Dampf"
CAT_TITLE   = "SearchTest Haushalt"
TAG_TITLE   = "SearchTest Kreditkarte"


def search_type(driver, value):
    el = driver.find_element(By.ID, "exp-search")
    el.clear()
    if value:
        el.send_keys(value)
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}))", el
    )
    time.sleep(CLICK_PACE)


def visible_titles(driver):
    cards = driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card")
    return [
        c.find_element(By.CSS_SELECTOR, ".exp-title").text
        for c in cards
        if c.value_of_css_property("display") != "none"
    ]


class TestExpensesSearch:

    # ── Setup ────────────────────────────────────────────────────────────────

    def test_84_00_setup(self, driver, w, ctx):
        cat = api_post("/api/v1/categories/", ctx, json={"title": CAT_TITLE})
        assert cat.status_code == 201
        ctx["s84_cat_id"] = cat.json()["id"]

        tag = api_post("/api/v1/tags/", ctx, json={"title": TAG_TITLE})
        assert tag.status_code == 201
        ctx["s84_tag_id"] = tag.json()["id"]

        a = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_ALPHA, "type": "expense", "value": "111.00",
            "date_due": TODAY, "settled": False,
            "payee": PAYEE_ALPHA,
            "category_id": ctx["s84_cat_id"],
            "tag_ids": [ctx["s84_tag_id"]],
        })
        assert a.status_code == 201
        ctx["s84_uid_a"] = a.json()["id"]

        b = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_BETA, "type": "expense", "value": "222.00",
            "date_due": TODAY, "settled": False,
            "payee": PAYEE_BETA,
        })
        assert b.status_code == 201
        ctx["s84_uid_b"] = b.json()["id"]

    # ── tag: filter ──────────────────────────────────────────────────────────

    def test_84_10_tag_prefix_shows_only_tagged(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_ALPHA)

        search_type(driver, "tag:searchtest")

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles), "Alpha (tagged) should be visible"
        assert not any(TITLE_BETA in t for t in titles), "Beta (no tag) should be hidden"

    def test_84_11_tag_quoted_multiword(self, driver, w, ctx):
        search_type(driver, f'tag:"{TAG_TITLE.lower()}"')

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    # ── cat: filter ──────────────────────────────────────────────────────────

    def test_84_20_cat_prefix_shows_only_categorised(self, driver, w, ctx):
        search_type(driver, "cat:searchtest")

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    def test_84_21_cat_quoted_multiword(self, driver, w, ctx):
        search_type(driver, f'cat:"{CAT_TITLE.lower()}"')

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    # ── payee: filter ────────────────────────────────────────────────────────

    def test_84_30_payee_prefix_single_word(self, driver, w, ctx):
        search_type(driver, "payee:rainer")

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    def test_84_31_payee_quoted_full_name(self, driver, w, ctx):
        search_type(driver, f'payee:"{PAYEE_ALPHA.lower()}"')

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    # ── combined filters ─────────────────────────────────────────────────────

    def test_84_40_combined_prefix_and_freetext(self, driver, w, ctx):
        """tag: filter combined with a plain term must both have to match."""
        search_type(driver, "tag:searchtest alpha")

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    def test_84_41_no_match_combination(self, driver, w, ctx):
        """A tag filter that doesn't match anything should hide all our cards."""
        search_type(driver, "tag:searchtest payee:dampf")

        titles = visible_titles(driver)
        assert not any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    # ── sessionStorage persistence ───────────────────────────────────────────

    def test_84_50_search_persists_after_edit_cancel(self, driver, w, ctx):
        """Typing a search term, clicking Edit, then Cancel restores the term."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_ALPHA)

        search_type(driver, "SearchTest Alpha")
        assert any(TITLE_ALPHA in t for t in visible_titles(driver))
        assert not any(TITLE_BETA in t for t in visible_titles(driver))

        # Navigate to the edit page for Alpha
        driver.get(_url(f"/budget/expenses/{ctx['s84_uid_a']}/edit/"))
        wait_text(driver, w, "Cancel")

        # Click Cancel – should go back via history.back()
        driver.find_element(By.CSS_SELECTOR, ".form-actions .btn-secondary").click()
        wait_text(driver, w, TITLE_ALPHA)
        time.sleep(CLICK_PACE)

        # Search input must still contain the term
        val = driver.find_element(By.ID, "exp-search").get_attribute("value")
        assert "SearchTest Alpha" in val, f"Expected search term restored, got: {val!r}"

        # Alpha visible, Beta hidden
        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    def test_84_51_search_clears_on_plain_navigation(self, driver, w, ctx):
        """Search term is cleared when navigating fresh to the expenses list (no expenses-area referrer)."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_ALPHA)
        search_type(driver, "SearchTest Beta")

        # Hard reload via driver.get — referrer is not within the expenses area,
        # so the search should be reset.
        driver.get(_url("/budget/dashboard/"))
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_ALPHA)
        time.sleep(CLICK_PACE)

        val = driver.find_element(By.ID, "exp-search").get_attribute("value")
        assert val == "", f"Expected empty search after plain navigation, got: {val!r}"

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert any(TITLE_BETA in t for t in titles)

    # ── ?search URL parameter ────────────────────────────────────────────────

    def test_84_60_url_param_tag_filter(self, driver, w, ctx):
        """?search=tag:"..." pre-fills the input and filters to matching expenses."""
        from urllib.parse import urlencode
        driver.execute_script("sessionStorage.removeItem('expSearch')")
        url = _url("/budget/expenses/") + "?" + urlencode({"search": f'tag:"{TAG_TITLE}"'})
        driver.get(url)
        wait_text(driver, w, TITLE_ALPHA)
        time.sleep(CLICK_PACE)

        val = driver.find_element(By.ID, "exp-search").get_attribute("value")
        assert "tag:" in val.lower() and "kreditkarte" in val.lower(), (
            f"Expected tag filter in search input, got: {val!r}"
        )

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    def test_84_61_url_param_cat_filter(self, driver, w, ctx):
        """?search=cat:"..." pre-fills the input and filters to matching expenses."""
        from urllib.parse import urlencode
        driver.execute_script("sessionStorage.removeItem('expSearch')")
        url = _url("/budget/expenses/") + "?" + urlencode({"search": f'cat:"{CAT_TITLE}"'})
        driver.get(url)
        wait_text(driver, w, TITLE_ALPHA)
        time.sleep(CLICK_PACE)

        val = driver.find_element(By.ID, "exp-search").get_attribute("value")
        assert "cat:" in val.lower() and "haushalt" in val.lower(), (
            f"Expected cat filter in search input, got: {val!r}"
        )

        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

    def test_84_62_url_param_overwrites_session_storage(self, driver, w, ctx):
        """?search URL param takes precedence over any existing sessionStorage value."""
        from urllib.parse import urlencode
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_ALPHA)
        # Seed sessionStorage with Beta's title so it would normally hide Alpha
        driver.execute_script("sessionStorage.setItem('expSearch', arguments[0])", TITLE_BETA)

        url = _url("/budget/expenses/") + "?" + urlencode({"search": f'tag:"{TAG_TITLE}"'})
        driver.get(url)
        wait_text(driver, w, TITLE_ALPHA)
        time.sleep(CLICK_PACE)

        # URL param must win — Alpha visible, Beta hidden
        titles = visible_titles(driver)
        assert any(TITLE_ALPHA in t for t in titles)
        assert not any(TITLE_BETA in t for t in titles)

        # sessionStorage must now reflect the URL param value
        stored = driver.execute_script("return sessionStorage.getItem('expSearch')")
        assert stored and "tag:" in stored.lower(), (
            f"Expected sessionStorage updated by URL param, got: {stored!r}"
        )

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def test_84_99_cleanup(self, driver, w, ctx):
        for key in ("s84_uid_a", "s84_uid_b"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)
        for key in ("s84_cat_id",):
            if key in ctx:
                api_delete(f"/api/v1/categories/{ctx.pop(key)}/", ctx)
        for key in ("s84_tag_id",):
            if key in ctx:
                api_delete(f"/api/v1/tags/{ctx.pop(key)}/", ctx)

        # Clear sessionStorage so leftover search term doesn't bleed into other tests
        driver.execute_script("sessionStorage.removeItem('expSearch')")
