"""
Deactivated/end_on behaviour.

1. A deactivated scheduled expense does not generate expense entries.
2. A scheduled expense with end_on set stops generating after that date.
3. A deactivated expense is excluded from the API dashboard totals.
"""
import re
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, fill, submit, wait_url, wait_text, server_today,
    api_get, api_post, api_delete, run_cmd,
    setup_user, cleanup_user,
)


def _expenses_by_title_year(ctx, title):
    resp = api_get("/api/v1/expenses/", ctx, params={"year": 2026, "view": "year"})
    assert resp.status_code == 200
    return [e for e in resp.json()["expenses"] if e["title"] == title]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestDeactivatedScheduler:

    def test_deactivated_generates_nothing(self, driver, w, ctx):
        """A deactivated scheduled expense must not produce any expense entries."""
        driver.get(_url("/budget/scheduled/new/"))
        fill(w, By.ID, "id_title", "DeactSched Test")
        fill(w, By.ID, "id_value", "50.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script("document.getElementById('id_repeat_base_date').value='2026-01-01';")
        driver.execute_script("document.getElementById('id_deactivated').checked=true;")
        submit(w)
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "DeactSched Test")

        ctx["deact_sched_uid"] = re.search(
            r'/scheduled/(\d+)/edit/',
            w.until(EC.element_to_be_clickable(
                (By.XPATH, "//span[contains(text(),'DeactSched Test')]"
                           "/ancestor::div[contains(@class,'exp-card')]"
                           "//a[contains(@href,'/edit/')]"))).get_attribute("href"),
        ).group(1)

        run_cmd("generate_scheduled_expenses", "--year", "2026")
        assert len(_expenses_by_title_year(ctx, "DeactSched Test")) == 0

    def test_deactivated_badge_shown(self, driver, w, ctx):
        driver.get(_url("/budget/scheduled/"))
        wait_text(driver, w, "DeactSched Test")
        assert "Deactivated" in driver.page_source

    def test_cleanup_deactivated_scheduler(self, driver, w, ctx):
        uid = ctx.pop("deact_sched_uid", None)
        if uid:
            api_delete(f"/api/v1/scheduled/{uid}/", ctx)


class TestEndOnScheduler:

    def test_end_on_stops_generation(self, driver, w, ctx):
        """Scheduler with end_on=2026-03-31 must not generate for April 2026."""
        sid = api_post("/api/v1/scheduled/", ctx, json={
            "title": "EndOn Test", "type": "expense", "value": "10.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": "2026-01-01", "end_on": "2026-03-31",
        }).json()["id"]

        run_cmd("generate_scheduled_expenses", "--year", "2026")
        resp = api_get("/api/v1/expenses/", ctx, params={"year": 2026, "month": 4})
        april = [e for e in resp.json()["expenses"] if e["title"] == "EndOn Test"]
        assert len(april) == 0, f"No entries expected for April, got: {april}"

        # March must have an entry
        resp_mar = api_get("/api/v1/expenses/", ctx, params={"year": 2026, "month": 3})
        march = [e for e in resp_mar.json()["expenses"] if e["title"] == "EndOn Test"]
        assert len(march) == 1

        for e in _expenses_by_title_year(ctx, "EndOn Test"):
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)


class TestDeactivatedExpense:

    def test_grayed_in_list(self, driver, w, ctx):
        """A deactivated expense shows the deactivated style and badge in the expense list."""
        from selenium.webdriver.support.ui import Select as _Select
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        fill(w, By.ID, "id_title", "Deact Expense Test")
        fill(w, By.ID, "id_value", "400.00")
        _Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
            "document.getElementById('id_deactivated').checked = true;"
        )
        submit(w)
        wait_url(w, "/budget/expenses/")
        time.sleep(2)
        src = driver.page_source
        assert "Deact Expense Test" in src, "Expense not found in list"
        assert "exp-card--deactivated" in src, "Deactivated style class missing"
        assert "Deactivated" in src, "Deactivated badge missing"
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Deact Expense Test", "view": "year"})
        for e in resp.json()["expenses"]:
            if e["title"] == "Deact Expense Test":
                api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
                break

    def test_excluded_from_dashboard(self, driver, w, ctx):
        """A deactivated expense must NOT appear in dashboard totals."""
        today = server_today()
        # Active settled expense
        active = api_post("/api/v1/expenses/", ctx, json={
            "title": "Deact Active", "type": "expense", "value": "100.00",
            "date_due": today, "settled": True,
        })
        assert active.status_code == 201
        active_id = active.json()["id"]

        dash_before = api_get("/api/v1/dashboard/", ctx).json()
        paid_before = float(dash_before["expenses_paid"])

        # Create a deactivated settled expense with same value
        deact = api_post("/api/v1/expenses/", ctx, json={
            "title": "Deact Hidden", "type": "expense", "value": "999.00",
            "date_due": today, "settled": True, "deactivated": True,
        })
        assert deact.status_code == 201
        deact_id = deact.json()["id"]

        dash_after = api_get("/api/v1/dashboard/", ctx).json()
        paid_after = float(dash_after["expenses_paid"])

        # Dashboard total must not have increased by 999
        assert paid_after < paid_before + 500, (
            f"Deactivated expense must not affect dashboard: before={paid_before} after={paid_after}")

        api_delete(f"/api/v1/expenses/{active_id}/", ctx)
        api_delete(f"/api/v1/expenses/{deact_id}/", ctx)
