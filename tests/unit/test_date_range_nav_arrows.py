"""
Unit tests for date range nav arrow button navigation logic.

The arrow buttons in templates/partials/_date_range_nav.html use _currentMode
(a persistent navigation mode) to shift date ranges. The mode is set when a
preset is selected and kept even when navigation lands outside known presets,
thanks to the _selfChange guard that prevents daterangechange from clobbering it.

These tests mirror the JS functions inlined in _date_range_nav.html.

Run with: venv/bin/pytest tests/unit/test_date_range_nav_arrows.py -v
"""

import calendar
from datetime import date, timedelta

import pytest


# ---------------------------------------------------------------------------
# JS logic inlined — mirrors _date_range_nav.html
# ---------------------------------------------------------------------------

def _preset_mode(key):
    if not key:
        return None
    if key in ('prev_fin_month', 'cur_fin_month', 'next_fin_month'):
        return 'fin_month'
    if key in ('prev_year', 'cur_year', 'next_year'):
        return 'cal_year'
    if key in ('q1', 'q2', 'q3', 'q4'):
        return 'quarter'
    return None


def _add_months(date_str, n):
    """Add n months to YYYY-MM-DD, clipping to the last valid day."""
    d = date.fromisoformat(date_str)
    month = d.month - 1 + n
    year  = d.year + month // 12
    month = month % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, max_day)).isoformat()


def _add_years(date_str, n):
    d = date.fromisoformat(date_str)
    return date(d.year + n, d.month, d.day).isoformat()


def _end_from_start(from_str, n):
    """Last day of the period starting at from_str spanning n months."""
    next_start = date.fromisoformat(_add_months(from_str, n))
    return (next_start - timedelta(days=1)).isoformat()


def _shift_range(from_str, to_str, current_mode, direction):
    """Shift a date range by one unit in the given direction (-1 or +1)."""
    if not current_mode:
        return None
    if current_mode == 'fin_month':
        new_from = _add_months(from_str, direction)
        new_to   = _end_from_start(new_from, 1)
    elif current_mode == 'cal_year':
        new_from = _add_years(from_str, direction)
        new_to   = _add_years(to_str, direction)
    elif current_mode == 'quarter':
        new_from = _add_months(from_str, direction * 3)
        new_to   = _end_from_start(new_from, 3)
    else:
        return None
    return {'from': new_from, 'to': new_to}


# ---------------------------------------------------------------------------
# _preset_mode
# ---------------------------------------------------------------------------

class TestPresetMode:
    def test_fin_month_keys(self):
        assert _preset_mode('prev_fin_month') == 'fin_month'
        assert _preset_mode('cur_fin_month')  == 'fin_month'
        assert _preset_mode('next_fin_month') == 'fin_month'

    def test_cal_year_keys(self):
        assert _preset_mode('prev_year') == 'cal_year'
        assert _preset_mode('cur_year')  == 'cal_year'
        assert _preset_mode('next_year') == 'cal_year'

    def test_quarter_keys(self):
        assert _preset_mode('q1') == 'quarter'
        assert _preset_mode('q2') == 'quarter'
        assert _preset_mode('q3') == 'quarter'
        assert _preset_mode('q4') == 'quarter'

    def test_empty_string_returns_none(self):
        assert _preset_mode('') is None

    def test_none_returns_none(self):
        assert _preset_mode(None) is None

    def test_unknown_key_returns_none(self):
        assert _preset_mode('custom') is None
        assert _preset_mode('fiscal_q1') is None


# ---------------------------------------------------------------------------
# _add_months
# ---------------------------------------------------------------------------

class TestAddMonths:
    def test_forward_one_month(self):
        assert _add_months('2025-01-01', 1) == '2025-02-01'

    def test_forward_across_year_boundary(self):
        assert _add_months('2025-12-01', 1) == '2026-01-01'

    def test_back_one_month(self):
        assert _add_months('2025-03-01', -1) == '2025-02-01'

    def test_back_across_year_boundary(self):
        assert _add_months('2025-01-01', -1) == '2024-12-01'

    def test_back_multiple_months(self):
        assert _add_months('2025-06-15', -5) == '2025-01-15'

    def test_forward_multiple_months(self):
        assert _add_months('2025-01-15', 11) == '2025-12-15'

    def test_clips_to_last_day_of_short_month(self):
        # Jan 31 + 1 month: Feb has 28 days in 2025 (not leap)
        assert _add_months('2025-01-31', 1) == '2025-02-28'

    def test_clips_to_last_day_leap_year(self):
        # Jan 31 + 1 month: Feb has 29 days in 2024 (leap)
        assert _add_months('2024-01-31', 1) == '2024-02-29'

    def test_quarter_hop_start_dates(self):
        # Quarter starts are always 1st; no clipping needed
        assert _add_months('2025-01-01', 3)  == '2025-04-01'
        assert _add_months('2025-04-01', 3)  == '2025-07-01'
        assert _add_months('2025-07-01', 3)  == '2025-10-01'
        assert _add_months('2025-10-01', 3)  == '2026-01-01'

    def test_zero_months(self):
        assert _add_months('2025-06-15', 0) == '2025-06-15'


# ---------------------------------------------------------------------------
# _end_from_start
# ---------------------------------------------------------------------------

class TestEndFromStart:
    def test_one_month_standard(self):
        # Feb 1 → Mar 1 − 1 day = Feb 28 (2025, non-leap)
        assert _end_from_start('2025-02-01', 1) == '2025-02-28'

    def test_one_month_leap_year(self):
        assert _end_from_start('2024-02-01', 1) == '2024-02-29'

    def test_one_month_31_day_month(self):
        assert _end_from_start('2025-01-01', 1) == '2025-01-31'

    def test_one_month_30_day_month(self):
        assert _end_from_start('2025-04-01', 1) == '2025-04-30'

    def test_one_month_mid_month_start(self):
        # Financial month starting on 15th
        assert _end_from_start('2025-01-15', 1) == '2025-02-14'
        assert _end_from_start('2025-02-15', 1) == '2025-03-14'

    def test_three_months_q1(self):
        assert _end_from_start('2025-01-01', 3) == '2025-03-31'

    def test_three_months_q2(self):
        assert _end_from_start('2025-04-01', 3) == '2025-06-30'

    def test_three_months_q3(self):
        assert _end_from_start('2025-07-01', 3) == '2025-09-30'

    def test_three_months_q4(self):
        assert _end_from_start('2025-10-01', 3) == '2025-12-31'

    def test_twelve_months_is_full_year(self):
        assert _end_from_start('2025-01-01', 12) == '2025-12-31'


# ---------------------------------------------------------------------------
# _shift_range — financial month
# ---------------------------------------------------------------------------

class TestShiftRangeFinMonth:
    def test_forward_from_jan(self):
        r = _shift_range('2025-01-01', '2025-01-31', 'fin_month', 1)
        assert r == {'from': '2025-02-01', 'to': '2025-02-28'}

    def test_backward_from_feb(self):
        r = _shift_range('2025-02-01', '2025-02-28', 'fin_month', -1)
        assert r == {'from': '2025-01-01', 'to': '2025-01-31'}

    def test_forward_across_year_boundary(self):
        r = _shift_range('2025-12-01', '2025-12-31', 'fin_month', 1)
        assert r == {'from': '2026-01-01', 'to': '2026-01-31'}

    def test_backward_across_year_boundary(self):
        r = _shift_range('2025-01-01', '2025-01-31', 'fin_month', -1)
        assert r == {'from': '2024-12-01', 'to': '2024-12-31'}

    def test_leap_year_feb(self):
        r = _shift_range('2024-01-01', '2024-01-31', 'fin_month', 1)
        assert r == {'from': '2024-02-01', 'to': '2024-02-29'}

    def test_non_first_start_day(self):
        # Financial month starting on 15th
        r = _shift_range('2025-01-15', '2025-02-14', 'fin_month', 1)
        assert r == {'from': '2025-02-15', 'to': '2025-03-14'}

    def test_non_first_start_day_backward(self):
        r = _shift_range('2025-02-15', '2025-03-14', 'fin_month', -1)
        assert r == {'from': '2025-01-15', 'to': '2025-02-14'}

    def test_chain_three_forward(self):
        # Simulate three arrow presses; mirrors mode-persistent navigation
        cur_from, cur_to = '2025-01-01', '2025-01-31'
        for expected_from, expected_to in [
            ('2025-02-01', '2025-02-28'),
            ('2025-03-01', '2025-03-31'),
            ('2025-04-01', '2025-04-30'),
        ]:
            r = _shift_range(cur_from, cur_to, 'fin_month', 1)
            assert r == {'from': expected_from, 'to': expected_to}
            cur_from, cur_to = r['from'], r['to']

    def test_chain_into_custom_territory_and_back(self):
        # Navigate far back (past known presets) then forward: mode still works
        cur_from, cur_to = '2025-06-01', '2025-06-30'
        for _ in range(6):
            r = _shift_range(cur_from, cur_to, 'fin_month', -1)
            cur_from, cur_to = r['from'], r['to']
        assert cur_from == '2024-12-01'
        assert cur_to   == '2024-12-31'
        # Confirm round-trip back forward
        for _ in range(6):
            r = _shift_range(cur_from, cur_to, 'fin_month', 1)
            cur_from, cur_to = r['from'], r['to']
        assert cur_from == '2025-06-01'
        assert cur_to   == '2025-06-30'


# ---------------------------------------------------------------------------
# _shift_range — calendar year
# ---------------------------------------------------------------------------

class TestShiftRangeCalYear:
    def test_forward(self):
        r = _shift_range('2025-01-01', '2025-12-31', 'cal_year', 1)
        assert r == {'from': '2026-01-01', 'to': '2026-12-31'}

    def test_backward(self):
        r = _shift_range('2025-01-01', '2025-12-31', 'cal_year', -1)
        assert r == {'from': '2024-01-01', 'to': '2024-12-31'}

    def test_chain_three_forward(self):
        cur_from, cur_to = '2024-01-01', '2024-12-31'
        for expected_year in (2025, 2026, 2027):
            r = _shift_range(cur_from, cur_to, 'cal_year', 1)
            assert r['from'] == f'{expected_year}-01-01'
            assert r['to']   == f'{expected_year}-12-31'
            cur_from, cur_to = r['from'], r['to']

    def test_custom_territory_still_shifts(self):
        # A custom year range (not matching prev/cur/next_year) still navigates
        r = _shift_range('2020-01-01', '2020-12-31', 'cal_year', 1)
        assert r == {'from': '2021-01-01', 'to': '2021-12-31'}


# ---------------------------------------------------------------------------
# _shift_range — quarter
# ---------------------------------------------------------------------------

class TestShiftRangeQuarter:
    def test_q1_forward_to_q2(self):
        r = _shift_range('2025-01-01', '2025-03-31', 'quarter', 1)
        assert r == {'from': '2025-04-01', 'to': '2025-06-30'}

    def test_q2_forward_to_q3(self):
        r = _shift_range('2025-04-01', '2025-06-30', 'quarter', 1)
        assert r == {'from': '2025-07-01', 'to': '2025-09-30'}

    def test_q3_forward_to_q4(self):
        r = _shift_range('2025-07-01', '2025-09-30', 'quarter', 1)
        assert r == {'from': '2025-10-01', 'to': '2025-12-31'}

    def test_q4_forward_wraps_to_next_year_q1(self):
        r = _shift_range('2025-10-01', '2025-12-31', 'quarter', 1)
        assert r == {'from': '2026-01-01', 'to': '2026-03-31'}

    def test_q2_backward_to_q1(self):
        r = _shift_range('2025-04-01', '2025-06-30', 'quarter', -1)
        assert r == {'from': '2025-01-01', 'to': '2025-03-31'}

    def test_q1_backward_wraps_to_prev_year_q4(self):
        r = _shift_range('2025-01-01', '2025-03-31', 'quarter', -1)
        assert r == {'from': '2024-10-01', 'to': '2024-12-31'}

    def test_chain_full_cycle(self):
        expected = [
            ('2025-04-01', '2025-06-30'),
            ('2025-07-01', '2025-09-30'),
            ('2025-10-01', '2025-12-31'),
            ('2026-01-01', '2026-03-31'),
        ]
        cur_from, cur_to = '2025-01-01', '2025-03-31'
        for exp_from, exp_to in expected:
            r = _shift_range(cur_from, cur_to, 'quarter', 1)
            assert r == {'from': exp_from, 'to': exp_to}
            cur_from, cur_to = r['from'], r['to']


# ---------------------------------------------------------------------------
# _shift_range — no mode (arrows disabled)
# ---------------------------------------------------------------------------

class TestShiftRangeNoMode:
    def test_none_mode_returns_none(self):
        assert _shift_range('2025-01-01', '2025-01-31', None, 1)  is None
        assert _shift_range('2025-01-01', '2025-01-31', None, -1) is None

    def test_empty_string_mode_returns_none(self):
        assert _shift_range('2025-01-01', '2025-01-31', '', 1) is None


# ---------------------------------------------------------------------------
# Mode persistence: the _selfChange fix
#
# The JS _currentMode is NOT reset when navigating into custom territory.
# The daterangechange listener is guarded by _selfChange so it cannot
# clobber the mode when the event was fired by our own _apply().
#
# These tests verify that _shift_range works on any valid YYYY-MM-DD range
# as long as the caller provides a mode — regardless of whether that range
# matches a known preset key.
# ---------------------------------------------------------------------------

class TestModePersistence:
    """
    Simulate the browser scenario: user picks a preset (mode is set),
    presses the arrow multiple times, and ends up outside known presets.
    The mode must survive; _shift_range must keep producing valid ranges.
    """

    def test_fin_month_far_past_is_still_navigable(self):
        # Five months before the earliest fin-month preset is still navigable
        r = _shift_range('2020-03-01', '2020-03-31', 'fin_month', 1)
        assert r == {'from': '2020-04-01', 'to': '2020-04-30'}

    def test_cal_year_far_future_is_still_navigable(self):
        r = _shift_range('2035-01-01', '2035-12-31', 'cal_year', 1)
        assert r == {'from': '2036-01-01', 'to': '2036-12-31'}

    def test_quarter_mid_history_is_still_navigable(self):
        r = _shift_range('2018-07-01', '2018-09-30', 'quarter', -1)
        assert r == {'from': '2018-04-01', 'to': '2018-06-30'}

    def test_fin_month_custom_range_navigates_by_mode_not_preset_match(self):
        # This range does NOT match any preset, but mode='fin_month' is kept
        # from a prior dropdown selection — arrows must still work
        custom_from = '2023-08-01'
        custom_to   = '2023-08-31'
        r = _shift_range(custom_from, custom_to, 'fin_month', 1)
        assert r == {'from': '2023-09-01', 'to': '2023-09-30'}

    def test_mode_change_resets_navigation_unit(self):
        # After switching from fin_month to cal_year, arrows shift by year
        r_month = _shift_range('2025-06-01', '2025-06-30', 'fin_month', 1)
        assert r_month['from'] == '2025-07-01'

        r_year  = _shift_range('2025-06-01', '2025-06-30', 'cal_year', 1)
        assert r_year['from'] == '2026-06-01'
