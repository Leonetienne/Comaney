"""
Allowance-transition cron tests.

Setup: standard month (start_day=1, prev_month=False).
Months are derived dynamically from server_today() so tests remain valid
regardless of when they run.

We create a 1000 income + 600 expense in the previous financial month,
leaving 400 unspent.  For each action we:
  1. Set the action via API PATCH.
  2. Clear allowance_transition_month so the cron thinks the month is new.
  3. Run apply_allowance_transitions.
  4. Assert the right record was (or wasn't) created.
  5. Clean up between tests.
"""
import time
from datetime import date

import pytest

from conftest import api_get, api_post, api_patch, api_delete, run_cmd, server_today

_today = date.fromisoformat(server_today())
CUR_YEAR  = _today.year
CUR_MONTH = _today.month
if CUR_MONTH == 1:
    PREV_YEAR  = CUR_YEAR - 1
    PREV_MONTH = 12
else:
    PREV_YEAR  = CUR_YEAR
    PREV_MONTH = CUR_MONTH - 1

INCOME_TITLE  = "AT Income Prev"
EXPENSE_TITLE = "AT Expense Prev"
PREV_INCOME   = date(PREV_YEAR, PREV_MONTH, 15).isoformat()
PREV_EXPENSE  = date(PREV_YEAR, PREV_MONTH, 20).isoformat()
LEFT          = "400.00"


def _setup_prev_month(ctx):
    """Create a 1000 income and 600 expense in the previous (March) financial month."""
    inc = api_post("/api/v1/expenses/", ctx, json={
        "title": INCOME_TITLE,
        "type": "income",
        "value": "1000.00",
        "date_due": PREV_INCOME,
        "settled": True,
    })
    assert inc.status_code == 201, inc.text

    exp = api_post("/api/v1/expenses/", ctx, json={
        "title": EXPENSE_TITLE,
        "type": "expense",
        "value": "600.00",
        "date_due": PREV_EXPENSE,
        "settled": True,
    })
    assert exp.status_code == 201, exp.text

    return inc.json()["id"], exp.json()["id"]


def _teardown_prev_month(ctx, inc_id, exp_id):
    api_delete(f"/api/v1/expenses/{inc_id}/", ctx)
    api_delete(f"/api/v1/expenses/{exp_id}/", ctx)


def _reset_action(ctx, action):
    resp = api_patch("/api/v1/account/", ctx, json={
        "unspent_allowance_action": action,
        "allowance_transition_month": "",
        "month_start_day": 1,
        "month_start_prev": False,
    })
    assert resp.status_code == 200, resp.text
    time.sleep(1)


def _run_transition():
    out = run_cmd("apply_allowance_transitions")
    time.sleep(1)
    return out


def _expenses_in_month(ctx, year, month):
    resp = api_get("/api/v1/expenses/", ctx, params={"year": year, "month": month})
    assert resp.status_code == 200, resp.text
    return resp.json()["expenses"]


def _find_by_type(expenses, typ):
    return [e for e in expenses if e["type"] == typ]


class TestAllowanceTransition:

    def test_71_do_nothing(self, driver, w, ctx):
        """With 'do_nothing', running the transition creates no savings or carry-over entry."""
        inc_id, exp_id = _setup_prev_month(ctx)
        time.sleep(1)

        _reset_action(ctx, "do_nothing")
        _run_transition()

        prev = _expenses_in_month(ctx, PREV_YEAR, PREV_MONTH)
        cur  = _expenses_in_month(ctx, CUR_YEAR,  CUR_MONTH)

        savings   = _find_by_type(prev, "savings_dep")
        carryover = _find_by_type(cur,  "carry_over")

        assert savings   == [], f"Expected no savings_dep, got {savings}"
        assert carryover == [], f"Expected no carry_over, got {carryover}"

        _teardown_prev_month(ctx, inc_id, exp_id)
        time.sleep(1)

    def test_72_deposit_savings(self, driver, w, ctx):
        """With 'deposit_savings', the unspent 400 must appear as a savings_dep in the previous month (PREV_MONTH)."""
        inc_id, exp_id = _setup_prev_month(ctx)
        time.sleep(1)

        _reset_action(ctx, "deposit_savings")
        _run_transition()

        prev = _expenses_in_month(ctx, PREV_YEAR, PREV_MONTH)
        savings = _find_by_type(prev, "savings_dep")

        assert len(savings) == 1, f"Expected exactly 1 savings_dep, got {savings}"
        assert savings[0]["value"] == LEFT, f"Expected value {LEFT}, got {savings[0]['value']}"

        # clean up
        api_delete(f"/api/v1/expenses/{savings[0]['id']}/", ctx)
        _teardown_prev_month(ctx, inc_id, exp_id)
        time.sleep(1)

    def test_73_carry_over(self, driver, w, ctx):
        """With 'carry_over', the unspent 400 must appear as a carry_over entry in the current month."""
        inc_id, exp_id = _setup_prev_month(ctx)
        time.sleep(1)

        _reset_action(ctx, "carry_over")
        _run_transition()

        cur = _expenses_in_month(ctx, CUR_YEAR, CUR_MONTH)
        carryover = _find_by_type(cur, "carry_over")

        assert len(carryover) == 1, f"Expected exactly 1 carry_over, got {carryover}"
        assert carryover[0]["value"] == LEFT, f"Expected value {LEFT}, got {carryover[0]['value']}"

        # carry_over is not deletable via API by design; delete via shell
        eid = carryover[0]["id"]
        run_cmd("shell", "-c",
            f"from budget.models import Expense; Expense.objects.filter(uid={eid}).delete()")
        _teardown_prev_month(ctx, inc_id, exp_id)
        time.sleep(1)

    def test_74_no_duplicate_on_second_run(self, driver, w, ctx):
        """Running the transition a second time in the same month must produce no new entries."""
        inc_id, exp_id = _setup_prev_month(ctx)
        time.sleep(1)

        _reset_action(ctx, "deposit_savings")
        _run_transition()
        time.sleep(1)
        # second run — allowance_transition_month is now set, should skip
        _run_transition()

        prev = _expenses_in_month(ctx, PREV_YEAR, PREV_MONTH)
        savings = _find_by_type(prev, "savings_dep")

        assert len(savings) == 1, f"Expected exactly 1 savings_dep after double run, got {savings}"

        api_delete(f"/api/v1/expenses/{savings[0]['id']}/", ctx)
        _teardown_prev_month(ctx, inc_id, exp_id)
        time.sleep(1)

    def test_75_no_entry_when_left_is_zero(self, driver, w, ctx):
        """When expenses exactly equal income (left=0), no transition entry is created."""
        # 500 income, 500 expense → left = 0
        inc = api_post("/api/v1/expenses/", ctx, json={
            "title": "AT Zero Income", "type": "income",
            "value": "500.00", "date_due": PREV_INCOME, "settled": True,
        })
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AT Zero Expense", "type": "expense",
            "value": "500.00", "date_due": PREV_EXPENSE, "settled": True,
        })
        assert inc.status_code == 201
        assert exp.status_code == 201
        time.sleep(1)

        _reset_action(ctx, "carry_over")
        _run_transition()

        cur = _expenses_in_month(ctx, CUR_YEAR, CUR_MONTH)
        carryover = _find_by_type(cur, "carry_over")
        assert carryover == [], f"Expected no carry_over for zero left, got {carryover}"

        api_delete(f"/api/v1/expenses/{inc.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{exp.json()['id']}/", ctx)

        # reset to neutral
        api_patch("/api/v1/account/", ctx, json={"unspent_allowance_action": "do_nothing"})
        time.sleep(1)
