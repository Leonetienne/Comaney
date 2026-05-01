"""
Cron command tests: financial year interpretation, scheduled expense generation,
duplicate prevention, and auto-settle behaviour.

All setup/teardown is done via the API so these tests don't depend on browser state.
Management commands are executed via docker exec.
"""
import time
from datetime import date, timedelta

from conftest import api_post, api_get, api_patch, api_delete, run_cmd, server_today


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_scheduled(ctx, **kwargs):
    defaults = {
        "type": "expense",
        "value": "10.00",
        "repeat_every_factor": 1,
        "repeat_every_unit": "months",
    }
    defaults.update(kwargs)
    resp = api_post("/api/v1/scheduled/", ctx, json=defaults)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_expense(ctx, **kwargs):
    defaults = {
        "type": "expense",
        "value": "10.00",
        "settled": False,
    }
    defaults.update(kwargs)
    resp = api_post("/api/v1/expenses/", ctx, json=defaults)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _expenses_by_title(ctx, title, year=None, month=None, view=None):
    """Return expenses matching title, optionally scoped to a financial month or year."""
    params = {}
    if year:
        params["year"] = year
    if month:
        params["month"] = month
    if view:
        params["view"] = view
    resp = api_get("/api/v1/expenses/", ctx, params=params or None)
    assert resp.status_code == 200
    return [e for e in resp.json()["expenses"] if e["title"] == title]


def _run_generate(year=None):
    if year:
        return run_cmd("generate_scheduled_expenses", "--year", str(year))
    return run_cmd("generate_scheduled_expenses")


def _run_auto_settle():
    return run_cmd("auto_settle_expenses")


# ---------------------------------------------------------------------------
# Financial year range interpretation
# ---------------------------------------------------------------------------

class TestFinancialYearInterpretation:
    """
    Verify that financial year boundaries are computed correctly by checking
    which occurrences the cron generates for a given --year override.
    """

    def test_70_standard_year_start_day_1(self, driver, w, ctx):
        """
        With month_start_day=1, prev_month=False:
        financial year 2026 = Jan 1 – Dec 31, 2026.
        A yearly schedule with base Jan 1 2026 fires; one with base Jan 1 2027 does not.
        """
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 1, "month_start_prev": False})

        sid_in  = _create_scheduled(ctx, title="Cron FY Std IN",
                                    repeat_base_date="2026-01-01", repeat_every_unit="years")
        sid_out = _create_scheduled(ctx, title="Cron FY Std OUT",
                                    repeat_base_date="2027-01-01", repeat_every_unit="years")

        _run_generate(year=2026)

        hits_in  = _expenses_by_title(ctx, "Cron FY Std IN",  year=2026, view="year")
        hits_out = _expenses_by_title(ctx, "Cron FY Std OUT", year=2026, view="year")

        assert len(hits_in) == 1, f"Expected 1 occurrence for Jan 1 2026 in year 2026, got {hits_in}"
        assert hits_in[0]["date_due"] == "2026-01-01"
        assert len(hits_out) == 0, f"Jan 1 2027 base should not fire in year 2026, got {hits_out}"

        api_delete(f"/api/v1/scheduled/{sid_in}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid_out}/", ctx)
        for e in hits_in:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

    def test_71_year_start_day_15(self, driver, w, ctx):
        """
        With month_start_day=15, prev_month=False:
        financial year 2026 = Jan 15, 2026 – Jan 14, 2027.
        A yearly base on Jan 14 2027 (last day) fires; Jan 15 2027 (next year start) does not.
        """
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 15, "month_start_prev": False})

        sid_in  = _create_scheduled(ctx, title="Cron FY15 IN",
                                    repeat_base_date="2027-01-14", repeat_every_unit="years")
        sid_out = _create_scheduled(ctx, title="Cron FY15 OUT",
                                    repeat_base_date="2027-01-15", repeat_every_unit="years")

        _run_generate(year=2026)

        hits_in  = _expenses_by_title(ctx, "Cron FY15 IN",  year=2026, view="year")
        hits_out = _expenses_by_title(ctx, "Cron FY15 OUT", year=2026, view="year")

        assert len(hits_in) == 1, f"Jan 14 2027 should be last day of FY2026, got {hits_in}"
        assert hits_in[0]["date_due"] == "2027-01-14"
        assert len(hits_out) == 0, f"Jan 15 2027 is start of FY2027, should not fire, got {hits_out}"

        api_delete(f"/api/v1/scheduled/{sid_in}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid_out}/", ctx)
        for e in hits_in:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

        api_patch("/api/v1/account/", ctx, json={"month_start_day": 1, "month_start_prev": False})

    def test_72_prev_month_flag_year(self, driver, w, ctx):
        """
        With month_start_day=27, prev_month=True:
        financial year 2026 = Dec 27, 2025 – Dec 26, 2026.
        Base Dec 27 2025 (first day) fires; base Dec 27 2026 (first day of FY2027) does not.
        """
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 27, "month_start_prev": True})

        sid_in  = _create_scheduled(ctx, title="Cron FYprev IN",
                                    repeat_base_date="2025-12-27", repeat_every_unit="years")
        sid_out = _create_scheduled(ctx, title="Cron FYprev OUT",
                                    repeat_base_date="2026-12-27", repeat_every_unit="years")

        _run_generate(year=2026)

        hits_in  = _expenses_by_title(ctx, "Cron FYprev IN",  year=2026, view="year")
        hits_out = _expenses_by_title(ctx, "Cron FYprev OUT", year=2026, view="year")

        assert len(hits_in) == 1, f"Dec 27 2025 should be first day of FY2026, got {hits_in}"
        assert hits_in[0]["date_due"] == "2025-12-27"
        assert len(hits_out) == 0, f"Dec 27 2026 is first day of FY2027, should not fire, got {hits_out}"

        api_delete(f"/api/v1/scheduled/{sid_in}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid_out}/", ctx)
        for e in hits_in:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

        api_patch("/api/v1/account/", ctx, json={"month_start_day": 1, "month_start_prev": False})


# ---------------------------------------------------------------------------
# Expense generation from scheduled
# ---------------------------------------------------------------------------

class TestScheduledGeneration:

    def test_73_cron_generates_expense_from_scheduled(self, driver, w, ctx):
        """Running the cron creates at least one expense for the current period."""
        today = server_today()
        _create_scheduled(ctx,
            title="Cron Gen Test",
            repeat_base_date=today,
            repeat_every_unit="months",
            value="55.55",
        )

        out = _run_generate()
        assert "Cron Gen Test" in out or "created" in out.lower()

        # Query current financial month — today's occurrence should be there
        expenses = _expenses_by_title(ctx, "Cron Gen Test")
        assert len(expenses) == 1
        e = expenses[0]
        assert e["value"] == "55.55"
        assert e["settled"] is False
        assert e["date_due"] == today
        ctx["cron_gen_expense_id"] = e["id"]

    def test_74_cron_no_duplicate_on_second_run(self, driver, w, ctx):
        """Running the cron a second time must not create duplicate expenses."""
        _run_generate()
        expenses = _expenses_by_title(ctx, "Cron Gen Test")
        assert len(expenses) == 1, f"Duplicate created: {expenses}"

    def test_75_generated_expense_inherits_all_fields(self, driver, w, ctx):
        """Verify that payee, note, and auto_settle_on_due_date are inherited."""
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "Cron Inherit Test",
            "type": "expense",
            "value": "11.11",
            "payee": "Cron Payee",
            "note": "Cron Note",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": server_today(),
            "default_auto_settle_on_due_date": True,
        })
        assert resp.status_code == 201
        sid2 = resp.json()["id"]

        _run_generate()

        expenses = _expenses_by_title(ctx, "Cron Inherit Test")
        assert len(expenses) == 1
        e = expenses[0]
        assert e["payee"] == "Cron Payee"
        assert e["note"] == "Cron Note"
        assert e["auto_settle_on_due_date"] is True

        api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid2}/", ctx)

    def test_76_month_end_clamping(self, driver, w, ctx):
        """
        Scheduled with base_date Jan 31 and monthly repeat:
        the February occurrence must clamp to Feb 28 (non-leap year).
        """
        sid = _create_scheduled(ctx,
            title="Cron Jan31 Clamp",
            repeat_base_date="2026-01-31",
            repeat_every_unit="months",
            value="9.99",
        )

        _run_generate(year=2026)

        feb_expenses = _expenses_by_title(ctx, "Cron Jan31 Clamp", year=2026, month=2)
        assert len(feb_expenses) == 1, f"Expected 1 expense in Feb 2026, got {feb_expenses}"
        assert feb_expenses[0]["date_due"] == "2026-02-28", (
            f"Expected Feb 28 (clamped), got {feb_expenses[0]['date_due']}")

        all_expenses = _expenses_by_title(ctx, "Cron Jan31 Clamp", year=2026, view="year")
        for e in all_expenses:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_77_weekly_repeat_multiple_occurrences(self, driver, w, ctx):
        """A weekly schedule produces multiple occurrences; April 2026 gets exactly 5."""
        sid = _create_scheduled(ctx,
            title="Cron Weekly",
            repeat_base_date="2026-04-01",
            repeat_every_unit="weeks",
            repeat_every_factor=1,
            value="5.00",
        )

        _run_generate(year=2026)

        # Apr 1, 8, 15, 22, 29 — 5 occurrences in April 2026
        april_expenses = _expenses_by_title(ctx, "Cron Weekly", year=2026, month=4)
        assert len(april_expenses) == 5, f"Expected 5 weekly occurrences in April, got {len(april_expenses)}"
        due_dates = sorted(e["date_due"] for e in april_expenses)
        assert due_dates == ["2026-04-01", "2026-04-08", "2026-04-15", "2026-04-22", "2026-04-29"]

        all_expenses = _expenses_by_title(ctx, "Cron Weekly", year=2026, view="year")
        for e in all_expenses:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_78_cleanup_cron_gen_data(self, driver, w, ctx):
        if "cron_gen_expense_id" in ctx:
            api_delete(f"/api/v1/expenses/{ctx['cron_gen_expense_id']}/", ctx)
        resp = api_get("/api/v1/scheduled/", ctx)
        if resp.status_code == 200:
            for s in resp.json()["scheduled"]:
                if s["title"] == "Cron Gen Test":
                    api_delete(f"/api/v1/scheduled/{s['id']}/", ctx)


# ---------------------------------------------------------------------------
# Auto-settle command
# ---------------------------------------------------------------------------

class TestAutoSettle:

    def test_79_auto_settle_past_due(self, driver, w, ctx):
        """Unsettled expense with auto_settle flag and past due date gets settled."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        eid = _create_expense(ctx,
            title="AutoSettle Past",
            date_due=yesterday,
            auto_settle_on_due_date=True,
            settled=False,
        )
        _run_auto_settle()
        time.sleep(1)
        resp = api_get(f"/api/v1/expenses/{eid}/", ctx)
        assert resp.json()["settled"] is True, "Expected settled=True after auto-settle run"
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_80_auto_settle_future_not_settled(self, driver, w, ctx):
        """Expense with future due date must NOT be settled even with the flag."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        eid = _create_expense(ctx,
            title="AutoSettle Future",
            date_due=tomorrow,
            auto_settle_on_due_date=True,
            settled=False,
        )
        _run_auto_settle()
        time.sleep(1)
        resp = api_get(f"/api/v1/expenses/{eid}/", ctx)
        assert resp.json()["settled"] is False, "Future expense must not be auto-settled"
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_81_auto_settle_flag_off_not_settled(self, driver, w, ctx):
        """Expense past due but WITHOUT the auto_settle flag must remain unsettled."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        eid = _create_expense(ctx,
            title="AutoSettle NoFlag",
            date_due=yesterday,
            auto_settle_on_due_date=False,
            settled=False,
        )
        _run_auto_settle()
        time.sleep(1)
        resp = api_get(f"/api/v1/expenses/{eid}/", ctx)
        assert resp.json()["settled"] is False, "Expense without flag must not be auto-settled"
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_82_auto_settle_already_settled_unchanged(self, driver, w, ctx):
        """An already-settled expense must not be affected (idempotent)."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        eid = _create_expense(ctx,
            title="AutoSettle AlreadySettled",
            date_due=yesterday,
            auto_settle_on_due_date=True,
            settled=True,
        )
        _run_auto_settle()
        time.sleep(1)
        resp = api_get(f"/api/v1/expenses/{eid}/", ctx)
        assert resp.json()["settled"] is True
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_83_auto_settle_skips_deactivated(self, driver, w, ctx):
        """Deactivated expense with auto_settle flag and past due date must NOT be settled."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        eid = _create_expense(ctx,
            title="AutoSettle Deactivated",
            date_due=yesterday,
            auto_settle_on_due_date=True,
            settled=False,
            deactivated=True,
        )
        _run_auto_settle()
        time.sleep(1)
        resp = api_get(f"/api/v1/expenses/{eid}/", ctx)
        assert resp.json()["settled"] is False, "Deactivated expense must not be auto-settled"
        api_delete(f"/api/v1/expenses/{eid}/", ctx)
