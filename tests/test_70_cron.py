"""
Cron command tests: financial month interpretation, scheduled expense generation,
duplicate prevention, and auto-settle behaviour.

All setup/teardown is done via the API so these tests don't depend on browser state.
Management commands are executed via docker exec.
"""
import time
from datetime import date, timedelta

from conftest import api_post, api_get, api_patch, api_delete, run_cmd


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


def _expenses_by_title(ctx, title, year=None, month=None):
    """Return all expenses matching title in the given (or current) financial month."""
    params = {"year": year, "month": month} if year and month else None
    resp = api_get("/api/v1/expenses/", ctx, params=params)
    assert resp.status_code == 200
    return [e for e in resp.json()["expenses"] if e["title"] == title]


def _run_generate(year=None, month=None):
    if year and month:
        return run_cmd("generate_scheduled_expenses", "--year", str(year), "--month", str(month))
    return run_cmd("generate_scheduled_expenses")


def _run_auto_settle():
    return run_cmd("auto_settle_expenses")


# ---------------------------------------------------------------------------
# Financial month range interpretation
# ---------------------------------------------------------------------------

class TestFinancialMonthInterpretation:
    """
    Verify that financial month boundaries are interpreted correctly by checking
    which occurrences the cron generates for a given --year/--month override.
    """

    def test_70_standard_month_start_day_1(self, driver, w, ctx):
        """
        With month_start_day=1, prev_month=False (the default for this test user),
        April 2026 financial month = Apr 1 – Apr 30.
        A scheduled expense with base_date = Apr 1 should fire in April.
        A base_date = May 1 should NOT fire for April.
        """
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 1, "month_start_prev": False})

        sid_in  = _create_scheduled(ctx, title="Cron FM Standard IN",
                                    repeat_base_date="2026-04-01", repeat_every_unit="months")
        sid_out = _create_scheduled(ctx, title="Cron FM Standard OUT",
                                    repeat_base_date="2026-05-01", repeat_every_unit="months")

        _run_generate(year=2026, month=4)

        hits_in  = _expenses_by_title(ctx, "Cron FM Standard IN")
        hits_out = _expenses_by_title(ctx, "Cron FM Standard OUT")

        assert len(hits_in) == 1, f"Expected 1 expense for April base, got {hits_in}"
        assert hits_in[0]["date_due"] == "2026-04-01"
        assert len(hits_out) == 0, f"Expected 0 for May base in April run, got {hits_out}"

        api_delete(f"/api/v1/scheduled/{sid_in}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid_out}/", ctx)
        for e in hits_in:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

    def test_71_month_start_day_15(self, driver, w, ctx):
        """
        With month_start_day=15, prev_month=False:
        April 2026 financial month = Apr 15 – May 14.
        base_date = Apr 15 fires in April FM.
        base_date = May 15 does NOT fire in April FM (first occurrence is May 15, in May FM).
        Note: Apr 14 is a bad OUT candidate — its next monthly occurrence is May 14,
        which lands inside April FM (Apr 15 – May 14).
        """
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 15, "month_start_prev": False})

        sid_in  = _create_scheduled(ctx, title="Cron FM15 IN",
                                    repeat_base_date="2026-04-15", repeat_every_unit="months")
        sid_out = _create_scheduled(ctx, title="Cron FM15 OUT",
                                    repeat_base_date="2026-05-15", repeat_every_unit="months")

        _run_generate(year=2026, month=4)

        hits_in  = _expenses_by_title(ctx, "Cron FM15 IN")
        hits_out = _expenses_by_title(ctx, "Cron FM15 OUT")

        assert len(hits_in) == 1, f"Expected 1 for Apr 15 base, got {hits_in}"
        assert hits_in[0]["date_due"] == "2026-04-15"
        assert len(hits_out) == 0, f"May 15 base should not fire in April FM, got {hits_out}"

        api_delete(f"/api/v1/scheduled/{sid_in}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid_out}/", ctx)
        for e in hits_in:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

        api_patch("/api/v1/account/", ctx, json={"month_start_day": 1, "month_start_prev": False})

    def test_72_prev_month_flag(self, driver, w, ctx):
        """
        With month_start_day=27, prev_month=True:
        April 2026 financial month = Mar 27 – Apr 26.
        base_date = Mar 27 fires; base_date = Apr 27 does NOT (it's in May FM).
        """
        api_patch("/api/v1/account/", ctx, json={"month_start_day": 27, "month_start_prev": True})

        sid_in  = _create_scheduled(ctx, title="Cron FMprev IN",
                                    repeat_base_date="2026-03-27", repeat_every_unit="months")
        sid_out = _create_scheduled(ctx, title="Cron FMprev OUT",
                                    repeat_base_date="2026-04-27", repeat_every_unit="months")

        _run_generate(year=2026, month=4)

        # Apr 29 falls in May FM with these settings; explicitly query April FM
        hits_in  = _expenses_by_title(ctx, "Cron FMprev IN",  year=2026, month=4)
        hits_out = _expenses_by_title(ctx, "Cron FMprev OUT", year=2026, month=4)

        assert len(hits_in) == 1, f"Expected 1 for Mar 27 base in April FM, got {hits_in}"
        assert hits_in[0]["date_due"] == "2026-03-27"
        assert len(hits_out) == 0, f"Apr 27 should be May FM, got {hits_out}"

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
        """Running the cron creates exactly one expense for the matching period."""
        today = date.today()
        _create_scheduled(ctx,
            title="Cron Gen Test",
            repeat_base_date=today.isoformat(),
            repeat_every_unit="months",
            value="55.55",
        )

        out = _run_generate()
        assert "Cron Gen Test" in out or "created" in out.lower()

        expenses = _expenses_by_title(ctx, "Cron Gen Test")
        assert len(expenses) == 1
        e = expenses[0]
        assert e["value"] == "55.55"
        assert e["settled"] is False
        assert e["date_due"] == today.isoformat()
        ctx["cron_gen_expense_id"] = e["id"]

    def test_74_cron_no_duplicate_on_second_run(self, driver, w, ctx):
        """Running the cron a second time must not create duplicate expenses."""
        _run_generate()
        expenses = _expenses_by_title(ctx, "Cron Gen Test")
        assert len(expenses) == 1, f"Duplicate created: {expenses}"

    def test_75_generated_expense_inherits_all_fields(self, driver, w, ctx):
        """Verify that payee, note, and auto_settle_on_due_date are inherited."""
        today = date.today()
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "Cron Inherit Test",
            "type": "expense",
            "value": "11.11",
            "payee": "Cron Payee",
            "note": "Cron Note",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": today.isoformat(),
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

        _run_generate(year=2026, month=2)

        expenses = _expenses_by_title(ctx, "Cron Jan31 Clamp", year=2026, month=2)
        assert len(expenses) == 1, f"Expected 1 expense in Feb 2026, got {expenses}"
        assert expenses[0]["date_due"] == "2026-02-28", (
            f"Expected Feb 28 (clamped), got {expenses[0]['date_due']}")

        api_delete(f"/api/v1/expenses/{expenses[0]['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_77_weekly_repeat_multiple_occurrences(self, driver, w, ctx):
        """A weekly schedule produces multiple occurrences within one month."""
        sid = _create_scheduled(ctx,
            title="Cron Weekly",
            repeat_base_date="2026-04-01",
            repeat_every_unit="weeks",
            repeat_every_factor=1,
            value="5.00",
        )

        _run_generate(year=2026, month=4)

        # Apr 1, 8, 15, 22, 29 — 5 occurrences in April 2026
        expenses = _expenses_by_title(ctx, "Cron Weekly")
        assert len(expenses) == 5, f"Expected 5 weekly occurrences in April, got {len(expenses)}"
        due_dates = sorted(e["date_due"] for e in expenses)
        assert due_dates == ["2026-04-01", "2026-04-08", "2026-04-15", "2026-04-22", "2026-04-29"]

        for e in expenses:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_78_cleanup_cron_gen_data(self, driver, w, ctx):
        if "cron_gen_expense_id" in ctx:
            api_delete(f"/api/v1/expenses/{ctx['cron_gen_expense_id']}/", ctx)
        # Clean up the "Cron Gen Test" scheduled (created without storing sid)
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
