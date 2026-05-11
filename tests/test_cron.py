"""
Cron command tests: scheduled expense generation, duplicate prevention,
auto-settle behaviour, and financial-year boundary interpretation.
"""
import time
from datetime import date, timedelta

import pytest

from helpers import (
    api_get, api_post, api_patch, api_delete, run_cmd, server_today,
    setup_user, cleanup_user,
)


def _create_scheduled(ctx, **kwargs):
    body = {"type": "expense", "value": "10.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months"}
    body.update(kwargs)
    resp = api_post("/api/v1/scheduled/", ctx, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_expense(ctx, **kwargs):
    body = {"type": "expense", "value": "10.00", "settled": False}
    body.update(kwargs)
    resp = api_post("/api/v1/expenses/", ctx, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _by_title(ctx, title, year=None, month=None, view=None):
    params = {}
    if year:   params["year"]  = year
    if month:  params["month"] = month
    if view:   params["view"]  = view
    resp = api_get("/api/v1/expenses/", ctx, params=params or None)
    assert resp.status_code == 200
    return [e for e in resp.json()["expenses"] if e["title"] == title]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


# ── Financial year boundaries ─────────────────────────────────────────────────

class TestFinancialYear:

    def test_standard_year_day1(self, driver, w, ctx):
        """month_start_day=1: FY2026 = Jan 1 to Dec 31. Base Jan 1 2026 fires; Jan 1 2027 does not."""
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 1, "month_start_prev": False})
        sid_in  = _create_scheduled(ctx, title="FY Std IN",
                                    repeat_base_date="2026-01-01", repeat_every_unit="years")
        sid_out = _create_scheduled(ctx, title="FY Std OUT",
                                    repeat_base_date="2027-01-01", repeat_every_unit="years")
        run_cmd("generate_scheduled_expenses", "--year", "2026")
        hits_in  = _by_title(ctx, "FY Std IN",  year=2026, view="year")
        hits_out = _by_title(ctx, "FY Std OUT", year=2026, view="year")
        assert len(hits_in) == 1 and hits_in[0]["date_due"] == "2026-01-01"
        assert len(hits_out) == 0
        api_delete(f"/api/v1/scheduled/{sid_in}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid_out}/", ctx)
        for e in hits_in:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

    def test_year_start_day15(self, driver, w, ctx):
        """month_start_day=15: FY2026 = Jan 15 2026 to Jan 14 2027. Jan 14 2027 fires; Jan 15 2027 does not."""
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 15, "month_start_prev": False})
        sid_in  = _create_scheduled(ctx, title="FY15 IN",
                                    repeat_base_date="2027-01-14", repeat_every_unit="years")
        sid_out = _create_scheduled(ctx, title="FY15 OUT",
                                    repeat_base_date="2027-01-15", repeat_every_unit="years")
        run_cmd("generate_scheduled_expenses", "--year", "2026")
        hits_in  = _by_title(ctx, "FY15 IN",  year=2026, view="year")
        hits_out = _by_title(ctx, "FY15 OUT", year=2026, view="year")
        assert len(hits_in) == 1 and hits_in[0]["date_due"] == "2027-01-14"
        assert len(hits_out) == 0
        api_delete(f"/api/v1/scheduled/{sid_in}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid_out}/", ctx)
        for e in hits_in:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 1, "month_start_prev": False})

    def test_prev_month_flag(self, driver, w, ctx):
        """month_start_day=27, prev_month=True: FY2026 = Dec 27 2025 to Dec 26 2026."""
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 27, "month_start_prev": True})
        sid_in  = _create_scheduled(ctx, title="FYprev IN",
                                    repeat_base_date="2025-12-27", repeat_every_unit="years")
        sid_out = _create_scheduled(ctx, title="FYprev OUT",
                                    repeat_base_date="2026-12-27", repeat_every_unit="years")
        run_cmd("generate_scheduled_expenses", "--year", "2026")
        hits_in  = _by_title(ctx, "FYprev IN",  year=2026, view="year")
        hits_out = _by_title(ctx, "FYprev OUT", year=2026, view="year")
        assert len(hits_in) == 1 and hits_in[0]["date_due"] == "2025-12-27"
        assert len(hits_out) == 0
        api_delete(f"/api/v1/scheduled/{sid_in}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid_out}/", ctx)
        for e in hits_in:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 1, "month_start_prev": False})


# ── Scheduled expense generation ──────────────────────────────────────────────

class TestScheduledGeneration:

    def test_generates_expense(self, driver, w, ctx):
        today = server_today()
        sid = _create_scheduled(ctx, title="CronGen Test",
                                repeat_base_date=today, value="55.55")
        run_cmd("generate_scheduled_expenses")
        expenses = _by_title(ctx, "CronGen Test")
        assert len(expenses) == 1
        e = expenses[0]
        assert e["value"] == "55.55"
        assert e["date_due"] == today
        ctx["cron_gen_eid"]  = e["id"]
        ctx["cron_gen_sid"]  = sid

    def test_no_duplicate_on_second_run(self, driver, w, ctx):
        run_cmd("generate_scheduled_expenses")
        assert len(_by_title(ctx, "CronGen Test")) == 1

    def test_inherits_fields(self, driver, w, ctx):
        sid = _create_scheduled(ctx, title="CronInherit",
                                repeat_base_date=server_today(), value="11.11",
                                payee="Cron Payee", note="Cron Note",
                                default_auto_settle_on_due_date=True)
        run_cmd("generate_scheduled_expenses")
        expenses = _by_title(ctx, "CronInherit")
        assert len(expenses) == 1
        e = expenses[0]
        assert e["payee"] == "Cron Payee"
        assert e["note"] == "Cron Note"
        assert e["auto_settle_on_due_date"] is True
        api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_month_end_clamping(self, driver, w, ctx):
        """Base Jan 31 with monthly repeat: Feb occurrence must clamp to Feb 28."""
        sid = _create_scheduled(ctx, title="CronClamp",
                                repeat_base_date="2026-01-31", value="9.99")
        run_cmd("generate_scheduled_expenses", "--year", "2026")
        feb = _by_title(ctx, "CronClamp", year=2026, month=2)
        assert len(feb) == 1
        assert feb[0]["date_due"] == "2026-02-28"
        for e in _by_title(ctx, "CronClamp", year=2026, view="year"):
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_weekly_multiple_occurrences(self, driver, w, ctx):
        """Weekly repeat: April 2026 has exactly 5 Wednesdays starting Apr 1."""
        sid = _create_scheduled(ctx, title="CronWeekly",
                                repeat_base_date="2026-04-01",
                                repeat_every_unit="weeks", repeat_every_factor=1, value="5.00")
        run_cmd("generate_scheduled_expenses", "--year", "2026")
        april = _by_title(ctx, "CronWeekly", year=2026, month=4)
        assert len(april) == 5
        assert sorted(e["date_due"] for e in april) == [
            "2026-04-01", "2026-04-08", "2026-04-15", "2026-04-22", "2026-04-29"]
        for e in _by_title(ctx, "CronWeekly", year=2026, view="year"):
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_cleanup(self, driver, w, ctx):
        for key in ("cron_gen_eid", "cron_gen_sid"):
            if key in ctx:
                path = "/api/v1/expenses/" if "eid" in key else "/api/v1/scheduled/"
                api_delete(f"{path}{ctx.pop(key)}/", ctx)


# ── Auto-settle ───────────────────────────────────────────────────────────────

class TestAutoSettle:

    def test_settles_past_due(self, driver, w, ctx):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        eid = _create_expense(ctx, title="AutoSettle Past",
                              date_due=yesterday, auto_settle_on_due_date=True)
        run_cmd("auto_settle_expenses")
        time.sleep(1)
        assert api_get(f"/api/v1/expenses/{eid}/", ctx).json()["settled"] is True
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_skips_future(self, driver, w, ctx):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        eid = _create_expense(ctx, title="AutoSettle Future",
                              date_due=tomorrow, auto_settle_on_due_date=True)
        run_cmd("auto_settle_expenses")
        time.sleep(1)
        assert api_get(f"/api/v1/expenses/{eid}/", ctx).json()["settled"] is False
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_skips_without_flag(self, driver, w, ctx):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        eid = _create_expense(ctx, title="AutoSettle NoFlag",
                              date_due=yesterday, auto_settle_on_due_date=False)
        run_cmd("auto_settle_expenses")
        time.sleep(1)
        assert api_get(f"/api/v1/expenses/{eid}/", ctx).json()["settled"] is False
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_skips_deactivated(self, driver, w, ctx):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        eid = _create_expense(ctx, title="AutoSettle Deact",
                              date_due=yesterday, auto_settle_on_due_date=True, deactivated=True)
        run_cmd("auto_settle_expenses")
        time.sleep(1)
        assert api_get(f"/api/v1/expenses/{eid}/", ctx).json()["settled"] is False
        api_delete(f"/api/v1/expenses/{eid}/", ctx)
