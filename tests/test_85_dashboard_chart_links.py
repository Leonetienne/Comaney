"""
Dashboard chart click-links.

Tests:
  - Clicking a category slice on the pie chart navigates to /budget/expenses/
    with a cat: search filter pre-applied.
  - Clicking a tag bar on the bar chart navigates to /budget/expenses/
    with a tag: search filter pre-applied.
  - After each navigation the search input is filled and expenses are filtered.

Chart clicks are simulated via Chart.js's public onClick handler so the test
does not depend on canvas pixel coordinates.
"""
import time
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from conftest import _url, wait_text, server_today, api_post, api_delete, CLICK_PACE


TODAY   = server_today()
CAT_TITLE = "ChartLink Haushalt"
TAG_TITLE = "ChartLink Kreditkarte"
TITLE_A   = "ChartLink Alpha"
TITLE_B   = "ChartLink Beta"


def visible_titles(driver):
    cards = driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card")
    return [
        c.find_element(By.CSS_SELECTOR, ".exp-title").text
        for c in cards
        if c.value_of_css_property("display") != "none"
    ]


def _wait_for_chart(w, chart_id):
    """Wait until Chart.js has finished initialising the given canvas."""
    w.until(lambda d: d.execute_script(
        "try { return !!Chart.getChart(document.getElementById(arguments[0])); }"
        " catch(e) { return false; }",
        chart_id,
    ))


def _chart_label_index(driver, chart_id, label):
    """Return the data index of *label* in the chart, or -1 if absent."""
    return driver.execute_script(
        "var c = Chart.getChart(document.getElementById(arguments[0]));"
        "return c ? c.data.labels.indexOf(arguments[1]) : -2;",
        chart_id, label,
    )


def _trigger_chart_click(driver, chart_id, index):
    """Invoke the chart's onClick handler for the element at *index*."""
    driver.execute_script(
        "var c = Chart.getChart(document.getElementById(arguments[0]));"
        "c.options.onClick(null, [{index: arguments[1]}]);",
        chart_id, index,
    )


class TestDashboardChartLinks:

    # ── Setup ────────────────────────────────────────────────────────────────

    def test_85_00_setup(self, driver, w, ctx):
        cat = api_post("/api/v1/categories/", ctx, json={"title": CAT_TITLE})
        assert cat.status_code == 201
        ctx["s85_cat_id"] = cat.json()["id"]

        tag = api_post("/api/v1/tags/", ctx, json={"title": TAG_TITLE})
        assert tag.status_code == 201
        ctx["s85_tag_id"] = tag.json()["id"]

        # Alpha has the test category + tag; Beta has neither
        a = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_A, "type": "expense", "value": "50.00",
            "date_due": TODAY, "settled": False,
            "category_id": ctx["s85_cat_id"],
            "tag_ids": [ctx["s85_tag_id"]],
        })
        assert a.status_code == 201
        ctx["s85_uid_a"] = a.json()["id"]

        b = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_B, "type": "expense", "value": "75.00",
            "date_due": TODAY, "settled": False,
        })
        assert b.status_code == 201
        ctx["s85_uid_b"] = b.json()["id"]

    # ── Category pie chart ───────────────────────────────────────────────────

    def test_85_10_cat_chart_click_navigates(self, driver, w, ctx):
        """Clicking a pie slice navigates to /budget/expenses/ with cat: filter."""
        driver.execute_script("sessionStorage.removeItem('expSearch')")
        driver.get(_url("/budget/"))
        w.until(EC.url_contains("/budget/"))
        _wait_for_chart(w, "cat-chart")

        idx = _chart_label_index(driver, "cat-chart", CAT_TITLE)
        assert idx >= 0, f"{CAT_TITLE!r} not found in cat-chart labels"

        _trigger_chart_click(driver, "cat-chart", idx)
        w.until(EC.url_contains("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        time.sleep(CLICK_PACE)

        val = driver.find_element(By.ID, "exp-search").get_attribute("value")
        assert "cat:" in val.lower() and "chartlink haushalt" in val.lower(), (
            f"Expected cat: filter in search input, got: {val!r}"
        )

        titles = visible_titles(driver)
        assert any(TITLE_A in t for t in titles), "Alpha (categorised) should be visible"
        assert not any(TITLE_B in t for t in titles), "Beta (uncategorised) should be hidden"

    # ── Tag bar chart ────────────────────────────────────────────────────────

    def test_85_20_tag_chart_click_navigates(self, driver, w, ctx):
        """Clicking a bar segment navigates to /budget/expenses/ with tag: filter."""
        driver.execute_script("sessionStorage.removeItem('expSearch')")
        driver.get(_url("/budget/"))
        w.until(EC.url_contains("/budget/"))
        _wait_for_chart(w, "tag-chart")

        idx = _chart_label_index(driver, "tag-chart", TAG_TITLE)
        assert idx >= 0, f"{TAG_TITLE!r} not found in tag-chart labels"

        _trigger_chart_click(driver, "tag-chart", idx)
        w.until(EC.url_contains("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        time.sleep(CLICK_PACE)

        val = driver.find_element(By.ID, "exp-search").get_attribute("value")
        assert "tag:" in val.lower() and "chartlink kreditkarte" in val.lower(), (
            f"Expected tag: filter in search input, got: {val!r}"
        )

        titles = visible_titles(driver)
        assert any(TITLE_A in t for t in titles), "Alpha (tagged) should be visible"
        assert not any(TITLE_B in t for t in titles), "Beta (untagged) should be hidden"

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def test_85_99_cleanup(self, driver, w, ctx):
        for key in ("s85_uid_a", "s85_uid_b"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)
        for key in ("s85_cat_id",):
            if key in ctx:
                api_delete(f"/api/v1/categories/{ctx.pop(key)}/", ctx)
        for key in ("s85_tag_id",):
            if key in ctx:
                api_delete(f"/api/v1/tags/{ctx.pop(key)}/", ctx)

        driver.execute_script("sessionStorage.removeItem('expSearch')")
