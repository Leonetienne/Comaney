"""
Allowance-transition cron tests.

Setup: 1000 income + 600 expense in the previous financial month = 400 unspent.
Each test configures one action, runs the cron, and checks what was (or was not) created.
Uses month_start_day=1, prev_month=False throughout.
"""
import time
from datetime import date

import pytest

from helpers import (
    api_get, api_post, api_patch, api_delete, run_cmd, server_today,
    setup_user, cleanup_user,
)

_today = date.fromisoformat(server_today())
CUR_YEAR   = _today.year
CUR_MONTH  = _today.month
PREV_YEAR  = CUR_YEAR - 1 if CUR_MONTH == 1 else CUR_YEAR
PREV_MONTH = 12           if CUR_MONTH == 1 else CUR_MONTH - 1
PREV_15    = date(PREV_YEAR, PREV_MONTH, 15).isoformat()
PREV_20    = date(PREV_YEAR, PREV_MONTH, 20).isoformat()
UNSPENT    = "400.00"


def _setup_prev_month(ctx):
    inc = api_post("/api/v1/expenses/", ctx, json={
        "title": "AT Income", "type": "income", "value": "1000.00",
        "date_due": PREV_15, "settled": True,
    })
    assert inc.status_code == 201
    exp = api_post("/api/v1/expenses/", ctx, json={
        "title": "AT Expense", "type": "expense", "value": "600.00",
        "date_due": PREV_20, "settled": True,
    })
    assert exp.status_code == 201
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
    assert resp.status_code == 200


def _expenses_in(ctx, year, month):
    resp = api_get("/api/v1/expenses/", ctx, params={"year": year, "month": month})
    assert resp.status_code == 200
    return resp.json()["expenses"]


def _by_type(expenses, typ):
    return [e for e in expenses if e["type"] == typ]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestAllowanceTransition:

    def test_do_nothing(self, driver, w, ctx):
        """do_nothing: no savings_dep entry is created for the previous month."""
        inc_id, exp_id = _setup_prev_month(ctx)
        time.sleep(1)
        _reset_action(ctx, "do_nothing")
        run_cmd("apply_allowance_transitions")
        time.sleep(1)
        assert _by_type(_expenses_in(ctx, PREV_YEAR, PREV_MONTH), "savings_dep") == []
        _teardown_prev_month(ctx, inc_id, exp_id)
        time.sleep(1)

    def test_deposit_savings(self, driver, w, ctx):
        """deposit_savings: 400 appears as savings_dep in the previous month."""
        inc_id, exp_id = _setup_prev_month(ctx)
        time.sleep(1)
        _reset_action(ctx, "deposit_savings")
        run_cmd("apply_allowance_transitions")
        time.sleep(1)
        savings = _by_type(_expenses_in(ctx, PREV_YEAR, PREV_MONTH), "savings_dep")
        assert len(savings) == 1
        assert savings[0]["value"] == UNSPENT
        api_delete(f"/api/v1/expenses/{savings[0]['id']}/", ctx)
        _teardown_prev_month(ctx, inc_id, exp_id)
        time.sleep(1)

    def test_no_duplicate_on_second_run(self, driver, w, ctx):
        """Running the transition twice in the same month must not create a second entry."""
        inc_id, exp_id = _setup_prev_month(ctx)
        time.sleep(1)
        _reset_action(ctx, "deposit_savings")
        run_cmd("apply_allowance_transitions")
        time.sleep(1)
        run_cmd("apply_allowance_transitions")
        time.sleep(1)
        savings = _by_type(_expenses_in(ctx, PREV_YEAR, PREV_MONTH), "savings_dep")
        assert len(savings) == 1, f"Expected 1 savings_dep, got {len(savings)}"
        api_delete(f"/api/v1/expenses/{savings[0]['id']}/", ctx)
        _teardown_prev_month(ctx, inc_id, exp_id)
        api_patch("/api/v1/account/", ctx, json={"unspent_allowance_action": "do_nothing"})

    def test_no_entry_when_left_is_zero(self, driver, w, ctx):
        """When income equals expenses (left=0), no transition entry is created."""
        inc = api_post("/api/v1/expenses/", ctx, json={
            "title": "AT Zero Income", "type": "income",
            "value": "500.00", "date_due": PREV_15, "settled": True,
        })
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AT Zero Expense", "type": "expense",
            "value": "500.00", "date_due": PREV_20, "settled": True,
        })
        assert inc.status_code == 201
        assert exp.status_code == 201
        time.sleep(1)
        _reset_action(ctx, "deposit_savings")
        run_cmd("apply_allowance_transitions")
        time.sleep(1)
        savings = _by_type(_expenses_in(ctx, PREV_YEAR, PREV_MONTH), "savings_dep")
        assert savings == [], f"Expected no savings_dep for zero left, got {savings}"
        api_delete(f"/api/v1/expenses/{inc.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{exp.json()['id']}/", ctx)
        api_patch("/api/v1/account/", ctx, json={"unspent_allowance_action": "do_nothing"})
        time.sleep(1)
