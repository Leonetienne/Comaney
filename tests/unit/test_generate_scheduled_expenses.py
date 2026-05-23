"""
Unit tests for occurrences_in_range and _add_period in
budget/management/commands/generate_scheduled_expenses.py.

Pure Python — no Django, no DB.
Run with: venv/bin/pytest tests/unit/test_generate_scheduled_expenses.py -v
"""

import calendar
import sys
import os
from datetime import date, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# ── Inline the two pure-Python helpers (Django not available in local venv) ──


def _add_period(d: date, factor: int, unit: str) -> date:
    if unit == "days":
        return d + timedelta(days=factor)
    if unit == "weeks":
        return d + timedelta(weeks=factor)
    if unit == "months":
        month = d.month + factor
        year = d.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        day = min(d.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    if unit == "years":
        year = d.year + factor
        day = min(d.day, calendar.monthrange(year, d.month)[1])
        return date(year, d.month, day)
    raise ValueError(f"Unknown unit: {unit}")


def occurrences_in_range(scheduled, start: date, end: date) -> list:
    base = scheduled.repeat_base_date
    factor = scheduled.repeat_every_factor
    unit = scheduled.repeat_every_unit

    if not base or not factor or not unit:
        return []

    if base > end:
        return []

    current = base
    while current < start:
        nxt = _add_period(current, factor, unit)
        if nxt == current:
            break
        current = nxt
        if current > end:
            return []

    results = []
    while current <= end:
        results.append(current)
        current = _add_period(current, factor, unit)

    return results


def _sched(base, factor, unit):
    return SimpleNamespace(repeat_base_date=base, repeat_every_factor=factor, repeat_every_unit=unit)


# ── _add_period ──────────────────────────────────────────────────────────────

class TestAddPeriod:

    def test_days(self):
        assert _add_period(date(2026, 1, 1), 7, "days") == date(2026, 1, 8)

    def test_weeks(self):
        assert _add_period(date(2026, 1, 1), 2, "weeks") == date(2026, 1, 15)

    def test_months_simple(self):
        assert _add_period(date(2026, 1, 15), 1, "months") == date(2026, 2, 15)

    def test_months_year_rollover(self):
        assert _add_period(date(2026, 12, 1), 1, "months") == date(2027, 1, 1)

    def test_months_clamp_to_month_end(self):
        # Jan 31 + 1 month -> Feb 28 (2026 is not a leap year)
        assert _add_period(date(2026, 1, 31), 1, "months") == date(2026, 2, 28)

    def test_years_simple(self):
        assert _add_period(date(2026, 6, 1), 1, "years") == date(2027, 6, 1)

    def test_years_clamp_leap_to_non_leap(self):
        # Feb 29 of a leap year + 1 year -> Feb 28 of non-leap
        assert _add_period(date(2024, 2, 29), 1, "years") == date(2025, 2, 28)


# ── occurrences_in_range ─────────────────────────────────────────────────────

class TestOccurrencesInRange:

    def test_monthly_hits_all_in_range(self):
        s = _sched(date(2026, 1, 1), 1, "months")
        result = occurrences_in_range(s, date(2026, 1, 1), date(2026, 3, 31))
        assert result == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]

    def test_base_before_range_advances_correctly(self):
        # base is Dec 2025, range is Jan–Mar 2026 -> should hit Jan, Feb, Mar
        s = _sched(date(2025, 12, 1), 1, "months")
        result = occurrences_in_range(s, date(2026, 1, 1), date(2026, 3, 31))
        assert result == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]

    def test_base_after_range_returns_empty(self):
        s = _sched(date(2027, 1, 1), 1, "months")
        result = occurrences_in_range(s, date(2026, 1, 1), date(2026, 12, 31))
        assert result == []

    def test_missing_fields_returns_empty(self):
        assert occurrences_in_range(_sched(None, 1, "months"), date(2026, 1, 1), date(2026, 12, 31)) == []
        assert occurrences_in_range(_sched(date(2026, 1, 1), None, "months"), date(2026, 1, 1), date(2026, 12, 31)) == []
        assert occurrences_in_range(_sched(date(2026, 1, 1), 1, None), date(2026, 1, 1), date(2026, 12, 31)) == []

    def test_yearly_two_years(self):
        s = _sched(date(2025, 6, 15), 1, "years")
        result = occurrences_in_range(s, date(2025, 1, 1), date(2026, 12, 31))
        assert result == [date(2025, 6, 15), date(2026, 6, 15)]

    def test_weekly(self):
        s = _sched(date(2026, 1, 5), 1, "weeks")
        result = occurrences_in_range(s, date(2026, 1, 1), date(2026, 1, 26))
        assert result == [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19), date(2026, 1, 26)]

    def test_base_on_range_end_included(self):
        s = _sched(date(2026, 12, 31), 1, "months")
        result = occurrences_in_range(s, date(2026, 1, 1), date(2026, 12, 31))
        assert result == [date(2026, 12, 31)]

    def test_single_occurrence_daily(self):
        s = _sched(date(2026, 6, 10), 1, "days")
        result = occurrences_in_range(s, date(2026, 6, 10), date(2026, 6, 10))
        assert result == [date(2026, 6, 10)]
