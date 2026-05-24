"""
Unit tests for date range preset generation, financial period arithmetic,
and query date-operator override semantics.

Run with: venv/bin/pytest tests/unit/test_date_range_presets.py -v
"""

import re
from datetime import date, timedelta

import pytest

from budget.date_utils import (
    current_financial_month,
    financial_month_range,
    financial_year_range,
)


# ---------------------------------------------------------------------------
# Inline preset builder — mirrors budget/views/_period.py without Django
# ---------------------------------------------------------------------------

def _build_presets(today_date, month_start_day=1, month_start_prev=False):
    """
    Build the date range presets dict for a given today and feuser settings.
    Mirrors _date_range_presets_context; returns {key: {'from': date, 'to': date, 'label': str}}.
    """
    sd, pm = month_start_day, month_start_prev
    cur_year = today_date.year

    def _cur_fin_month():
        for delta in (0, 1, -1, 2, -2):
            m = today_date.month + delta
            y = today_date.year
            if m < 1:    m += 12; y -= 1
            elif m > 12: m -= 12; y += 1
            start, end = financial_month_range(y, m, sd, pm)
            if start <= today_date <= end:
                return y, m
        return today_date.year, today_date.month

    cur_fin_year, cur_fin_month_num = _cur_fin_month()

    def _prev(y, m):
        m -= 1
        if m < 1: m = 12; y -= 1
        return y, m

    def _next(y, m):
        m += 1
        if m > 12: m = 1; y += 1
        return y, m

    prev_y, prev_m = _prev(cur_fin_year, cur_fin_month_num)
    next_y, next_m = _next(cur_fin_year, cur_fin_month_num)

    cf_s,  cf_e  = financial_month_range(cur_fin_year, cur_fin_month_num, sd, pm)
    pf_s,  pf_e  = financial_month_range(prev_y, prev_m, sd, pm)
    nf_s,  nf_e  = financial_month_range(next_y, next_m, sd, pm)

    def _mlabel(y, m): return date(y, m, 1).strftime("%b")

    return {
        "prev_fin_month": {"label": "Fin." + _mlabel(prev_y, prev_m), "from": pf_s, "to": pf_e},
        "cur_fin_month":  {"label": "Fin." + _mlabel(cur_fin_year, cur_fin_month_num), "from": cf_s, "to": cf_e},
        "next_fin_month": {"label": "Fin." + _mlabel(next_y, next_m), "from": nf_s, "to": nf_e},
        "prev_year": {"label": str(cur_year - 1),
                      "from": date(cur_year - 1, 1, 1), "to": date(cur_year - 1, 12, 31)},
        "cur_year":  {"label": str(cur_year),
                      "from": date(cur_year, 1, 1),     "to": date(cur_year, 12, 31)},
        "next_year": {"label": str(cur_year + 1),
                      "from": date(cur_year + 1, 1, 1), "to": date(cur_year + 1, 12, 31)},
        "q1": {"label": "Q1", "from": date(cur_year, 1, 1),  "to": date(cur_year, 3, 31)},
        "q2": {"label": "Q2", "from": date(cur_year, 4, 1),  "to": date(cur_year, 6, 30)},
        "q3": {"label": "Q3", "from": date(cur_year, 7, 1),  "to": date(cur_year, 9, 30)},
        "q4": {"label": "Q4", "from": date(cur_year, 10, 1), "to": date(cur_year, 12, 31)},
    }


# ---------------------------------------------------------------------------
# Inline has_date_filter from budget/query_parser.py (no Django needed)
# ---------------------------------------------------------------------------

def _has_date_filter(query_str: str) -> bool:
    return bool(re.search(r'\bdate\s*(?:==|[<>]=?)', query_str or ''))


# ---------------------------------------------------------------------------
# Inline the operator->ORM-lookup map from budget/query_parser._date_q
# Tests the semantics without needing Django Q objects.
# ---------------------------------------------------------------------------

_DATE_LOOKUP_MAP = {
    '<':  'lt',
    '<=': 'lte',
    '>':  'gt',
    '>=': 'gte',
    '=':  'exact',
    '==': 'exact',
}


def _date_lookup(op: str) -> str:
    return _DATE_LOOKUP_MAP.get(op, 'exact')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _is_disjoint(ranges: list[tuple[date, date]]) -> bool:
    seen = set()
    for s, e in ranges:
        for d in _all_dates(s, e):
            if d in seen:
                return False
            seen.add(d)
    return True


def _union(ranges: list[tuple[date, date]]) -> set[date]:
    return {d for s, e in ranges for d in _all_dates(s, e)}


def _expected(start: date, end: date) -> set[date]:
    return set(_all_dates(start, end))


# ============================================================================
# financial_month_range
# ============================================================================

class TestFinancialMonthRange:

    # -- Standard calendar months (sd=1, pm=False) ---------------------------

    @pytest.mark.parametrize("month, last_day", [
        (1, 31), (2, 28), (3, 31), (4, 30), (5, 31), (6, 30),
        (7, 31), (8, 31), (9, 30), (10, 31), (11, 30), (12, 31),
    ])
    def test_standard_calendar_months_2025(self, month, last_day):
        s, e = financial_month_range(2025, month, 1, False)
        assert s == date(2025, month, 1)
        assert e == date(2025, month, last_day)

    def test_standard_february_leap_year(self):
        s, e = financial_month_range(2024, 2, 1, False)
        assert s == date(2024, 2, 1)
        assert e == date(2024, 2, 29)  # 2024 is a leap year

    def test_standard_february_non_leap_year(self):
        s, e = financial_month_range(2025, 2, 1, False)
        assert e == date(2025, 2, 28)

    # -- Non-standard: start_day on prev month (sd=27, pm=True) --------------

    def test_prev_month_april_starts_mar27(self):
        s, e = financial_month_range(2025, 4, 27, True)
        assert s == date(2025, 3, 27)
        assert e == date(2025, 4, 26)

    def test_prev_month_january_crosses_year(self):
        # Jan financial month starts Dec 27 of prev year
        s, e = financial_month_range(2025, 1, 27, True)
        assert s == date(2024, 12, 27)
        assert e == date(2025, 1, 26)

    def test_prev_month_december(self):
        s, e = financial_month_range(2025, 12, 27, True)
        assert s == date(2025, 11, 27)
        assert e == date(2025, 12, 26)

    # -- Non-standard: start_day in current month (sd=15, pm=False) ----------

    def test_curr_month_start_april_starts_apr15(self):
        s, e = financial_month_range(2025, 4, 15, False)
        assert s == date(2025, 4, 15)
        assert e == date(2025, 5, 14)

    def test_curr_month_december_crosses_year(self):
        s, e = financial_month_range(2025, 12, 15, False)
        assert s == date(2025, 12, 15)
        assert e == date(2026, 1, 14)

    # -- start_day clamping for short months ---------------------------------

    def test_clamping_sd31_february_2025(self):
        # Feb has 28 days; sd=31 should clamp start to Feb 28
        s, e = financial_month_range(2025, 2, 31, False)
        assert s == date(2025, 2, 28)

    def test_clamping_sd31_february_leap(self):
        s, e = financial_month_range(2024, 2, 31, False)
        assert s == date(2024, 2, 29)

    # -- Adjacent months are seamless (no gap, no overlap) -------------------

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_adjacent_months_no_gap(self, sd, pm):
        for month in range(1, 12):
            _, e1 = financial_month_range(2025, month, sd, pm)
            s2, _ = financial_month_range(2025, month + 1, sd, pm)
            assert e1 + timedelta(days=1) == s2, (
                f"Gap between month {month} and {month+1} for sd={sd} pm={pm}: "
                f"end={e1}, next_start={s2}"
            )

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_adjacent_months_no_overlap(self, sd, pm):
        for month in range(1, 12):
            s1, e1 = financial_month_range(2025, month, sd, pm)
            s2, e2 = financial_month_range(2025, month + 1, sd, pm)
            assert e1 < s2, (
                f"Overlap between month {month} and {month+1}: "
                f"end={e1}, next_start={s2}"
            )


# ============================================================================
# financial_year_range
# ============================================================================

class TestFinancialYearRange:

    def test_standard_year_is_jan1_to_dec31(self):
        s, e = financial_year_range(2025, 1, False)
        assert s == date(2025, 1, 1)
        assert e == date(2025, 12, 31)

    def test_nonstandard_year_sd27_pm_true(self):
        # Financial Jan 2025 starts Dec 27 2024; Financial Dec 2025 ends Dec 26 2025
        s, e = financial_year_range(2025, 27, True)
        assert s == date(2024, 12, 27)
        assert e == date(2025, 12, 26)

    def test_nonstandard_year_sd15_pm_false(self):
        # Financial Jan 2025 starts Jan 15; Financial Dec 2025 ends Jan 14 2026
        s, e = financial_year_range(2025, 15, False)
        assert s == date(2025, 1, 15)
        assert e == date(2026, 1, 14)

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_year_equals_union_of_12_months(self, sd, pm):
        year_s, year_e = financial_year_range(2025, sd, pm)
        month_ranges = [financial_month_range(2025, m, sd, pm) for m in range(1, 13)]
        assert _union(month_ranges) == _expected(year_s, year_e)

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_year_start_equals_jan_month_start(self, sd, pm):
        jan_s, _ = financial_month_range(2025, 1, sd, pm)
        year_s, _ = financial_year_range(2025, sd, pm)
        assert year_s == jan_s

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_year_end_equals_dec_month_end(self, sd, pm):
        _, dec_e = financial_month_range(2025, 12, sd, pm)
        _, year_e = financial_year_range(2025, sd, pm)
        assert year_e == dec_e


# ============================================================================
# Preset date range values
# ============================================================================

class TestPresetDateRangeValues:

    TODAY = date(2026, 6, 13)

    def _p(self, **kw):
        return _build_presets(self.TODAY, **kw)

    # -- Quarters ------------------------------------------------------------

    def test_q1_range(self):
        p = self._p()
        assert p["q1"]["from"] == date(2026, 1, 1)
        assert p["q1"]["to"]   == date(2026, 3, 31)

    def test_q2_range(self):
        p = self._p()
        assert p["q2"]["from"] == date(2026, 4, 1)
        assert p["q2"]["to"]   == date(2026, 6, 30)

    def test_q3_range(self):
        p = self._p()
        assert p["q3"]["from"] == date(2026, 7, 1)
        assert p["q3"]["to"]   == date(2026, 9, 30)

    def test_q4_range(self):
        p = self._p()
        assert p["q4"]["from"] == date(2026, 10, 1)
        assert p["q4"]["to"]   == date(2026, 12, 31)

    # -- Calendar year presets are NOT financial years -----------------------

    def test_cur_year_is_jan1_to_dec31(self):
        p = self._p()
        assert p["cur_year"]["from"] == date(2026, 1, 1)
        assert p["cur_year"]["to"]   == date(2026, 12, 31)

    def test_prev_year_is_jan1_to_dec31(self):
        p = self._p()
        assert p["prev_year"]["from"] == date(2025, 1, 1)
        assert p["prev_year"]["to"]   == date(2025, 12, 31)

    def test_next_year_is_jan1_to_dec31(self):
        p = self._p()
        assert p["next_year"]["from"] == date(2027, 1, 1)
        assert p["next_year"]["to"]   == date(2027, 12, 31)

    def test_year_presets_are_calendar_years_nonstandard_settings(self):
        # Even with non-standard financial month settings, year presets are calendar years
        for sd, pm in [(15, False), (27, True)]:
            p = _build_presets(self.TODAY, sd, pm)
            assert p["cur_year"]["from"].month == 1
            assert p["cur_year"]["from"].day   == 1
            assert p["cur_year"]["to"].month   == 12
            assert p["cur_year"]["to"].day     == 31

    def test_year_labels_are_calendar_year_numbers(self):
        p = self._p()
        assert p["prev_year"]["label"] == "2025"
        assert p["cur_year"]["label"]  == "2026"
        assert p["next_year"]["label"] == "2027"

    # -- Financial month presets ---------------------------------------------

    def test_cur_fin_month_contains_today_standard(self):
        p = self._p()
        assert p["cur_fin_month"]["from"] <= self.TODAY <= p["cur_fin_month"]["to"]

    def test_prev_fin_month_ends_before_cur_starts(self):
        p = self._p()
        assert p["prev_fin_month"]["to"] < p["cur_fin_month"]["from"]

    def test_cur_fin_month_ends_before_next_starts(self):
        p = self._p()
        assert p["cur_fin_month"]["to"] < p["next_fin_month"]["from"]

    def test_cur_fin_month_contains_today_nonstandard(self):
        for sd, pm in [(15, False), (27, True)]:
            p = _build_presets(self.TODAY, sd, pm)
            assert p["cur_fin_month"]["from"] <= self.TODAY <= p["cur_fin_month"]["to"], (
                f"Today {self.TODAY} not in cur_fin_month for sd={sd} pm={pm}: "
                f"{p['cur_fin_month']['from']} – {p['cur_fin_month']['to']}"
            )

    def test_prev_fin_month_sd27_pm_true(self):
        # Today = 2026-06-13; cur fin month (sd=27, pm=True) = May 27 – Jun 26.
        # Prev fin month = Apr 27 – May 26.
        p = _build_presets(self.TODAY, 27, True)
        assert p["prev_fin_month"]["from"] == date(2026, 4, 27)
        assert p["prev_fin_month"]["to"]   == date(2026, 5, 26)

    def test_cur_fin_month_sd27_pm_true(self):
        p = _build_presets(self.TODAY, 27, True)
        assert p["cur_fin_month"]["from"] == date(2026, 5, 27)
        assert p["cur_fin_month"]["to"]   == date(2026, 6, 26)

    def test_next_fin_month_sd27_pm_true(self):
        p = _build_presets(self.TODAY, 27, True)
        assert p["next_fin_month"]["from"] == date(2026, 6, 27)
        assert p["next_fin_month"]["to"]   == date(2026, 7, 26)


# ============================================================================
# Preset disjointness
# ============================================================================

class TestPresetDisjointness:

    TODAY = date(2026, 6, 13)

    def _p(self, **kw):
        return _build_presets(self.TODAY, **kw)

    # -- Quarters ------------------------------------------------------------

    def test_quarters_are_pairwise_disjoint(self):
        p = self._p()
        qs = [(p[k]["from"], p[k]["to"]) for k in ("q1", "q2", "q3", "q4")]
        assert _is_disjoint(qs)

    def test_quarters_cover_full_calendar_year(self):
        p = self._p()
        year = self.TODAY.year
        qs = [(p[k]["from"], p[k]["to"]) for k in ("q1", "q2", "q3", "q4")]
        assert _union(qs) == _expected(date(year, 1, 1), date(year, 12, 31))

    def test_quarters_no_gap_between_adjacent(self):
        p = self._p()
        keys = ("q1", "q2", "q3", "q4")
        for i in range(len(keys) - 1):
            e = p[keys[i]]["to"]
            s = p[keys[i + 1]]["from"]
            assert e + timedelta(days=1) == s, f"Gap between {keys[i]} and {keys[i+1]}"

    # -- Financial months: standard ------------------------------------------

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_12_financial_months_disjoint(self, sd, pm):
        months = [financial_month_range(2025, m, sd, pm) for m in range(1, 13)]
        assert _is_disjoint(months), f"Overlap in financial months sd={sd} pm={pm}"

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_12_financial_months_cover_year(self, sd, pm):
        months = [financial_month_range(2025, m, sd, pm) for m in range(1, 13)]
        year_s, year_e = financial_year_range(2025, sd, pm)
        assert _union(months) == _expected(year_s, year_e)

    # -- Preset financial month trio (prev, cur, next) -----------------------

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_preset_fin_months_disjoint(self, sd, pm):
        p = _build_presets(self.TODAY, sd, pm)
        trio = [(p[k]["from"], p[k]["to"]) for k in ("prev_fin_month", "cur_fin_month", "next_fin_month")]
        assert _is_disjoint(trio)

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_preset_fin_months_sequential(self, sd, pm):
        p = _build_presets(self.TODAY, sd, pm)
        assert p["prev_fin_month"]["to"] + timedelta(days=1) == p["cur_fin_month"]["from"]
        assert p["cur_fin_month"]["to"]  + timedelta(days=1) == p["next_fin_month"]["from"]

    # -- Year presets --------------------------------------------------------

    def test_year_presets_disjoint(self):
        p = self._p()
        yr = [(p[k]["from"], p[k]["to"]) for k in ("prev_year", "cur_year", "next_year")]
        assert _is_disjoint(yr)

    def test_year_presets_sequential(self):
        p = self._p()
        assert p["prev_year"]["to"] + timedelta(days=1) == p["cur_year"]["from"]
        assert p["cur_year"]["to"]  + timedelta(days=1) == p["next_year"]["from"]


# ============================================================================
# All presets satisfy from <= to
# ============================================================================

class TestPresetFromLeTo:

    TODAY = date(2026, 6, 13)

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True), (31, False)])
    def test_all_presets_from_le_to(self, sd, pm):
        p = _build_presets(self.TODAY, sd, pm)
        for key, v in p.items():
            assert v["from"] <= v["to"], (
                f"Preset '{key}' has from > to: {v['from']} > {v['to']} (sd={sd}, pm={pm})"
            )

    @pytest.mark.parametrize("today", [
        date(2025, 1, 1),   # start of year
        date(2025, 12, 31), # end of year
        date(2025, 2, 28),  # end of February (non-leap)
        date(2024, 2, 29),  # leap day
        date(2025, 3, 27),  # exactly at a non-standard boundary
    ])
    def test_from_le_to_edge_dates(self, today):
        for sd, pm in [(1, False), (27, True), (15, False)]:
            p = _build_presets(today, sd, pm)
            for key, v in p.items():
                assert v["from"] <= v["to"], (
                    f"Preset '{key}' has from > to on today={today} sd={sd} pm={pm}"
                )

    def test_single_day_range_is_valid(self):
        # A from == to range is valid: it represents a single day.
        assert date(2026, 6, 13) <= date(2026, 6, 13)

    def test_inverted_range_is_empty(self):
        # from > to: the date range contains no days.
        # This documents the expected behavior: such a selection yields 0 results
        # because no date d satisfies (d >= from AND d <= to) when from > to.
        start = date(2026, 6, 30)
        end   = date(2026, 6, 1)
        assert start > end
        result = list(_all_dates(start, end))
        assert result == [], "Inverted range must produce an empty set of dates"

    @pytest.mark.parametrize("sd,pm", [(1, False), (15, False), (27, True)])
    def test_financial_months_all_from_le_to(self, sd, pm):
        for year in (2024, 2025, 2026):  # includes a leap year
            for month in range(1, 13):
                s, e = financial_month_range(year, month, sd, pm)
                assert s <= e, f"financial_month_range({year},{month},{sd},{pm}): {s} > {e}"


# ============================================================================
# Preset button/key ordering
# ============================================================================

class TestPresetButtonOrder:

    TODAY = date(2026, 6, 13)

    EXPECTED_ORDER = [
        "prev_fin_month",
        "cur_fin_month",
        "next_fin_month",
        "prev_year",
        "cur_year",
        "next_year",
        "q1", "q2", "q3", "q4",
    ]

    def test_preset_dict_key_order(self):
        p = _build_presets(self.TODAY)
        assert list(p.keys()) == self.EXPECTED_ORDER

    def test_fin_months_before_years_before_quarters(self):
        p = _build_presets(self.TODAY)
        keys = list(p.keys())
        # All fin_month presets come before year presets
        fin_idx = [keys.index(k) for k in ("prev_fin_month", "cur_fin_month", "next_fin_month")]
        yr_idx  = [keys.index(k) for k in ("prev_year", "cur_year", "next_year")]
        q_idx   = [keys.index(k) for k in ("q1", "q2", "q3", "q4")]
        assert max(fin_idx) < min(yr_idx)
        assert max(yr_idx)  < min(q_idx)

    def test_year_order_prev_cur_next(self):
        p = _build_presets(self.TODAY)
        keys = list(p.keys())
        assert keys.index("prev_year") < keys.index("cur_year") < keys.index("next_year")

    def test_fin_month_order_prev_cur_next(self):
        p = _build_presets(self.TODAY)
        keys = list(p.keys())
        assert keys.index("prev_fin_month") < keys.index("cur_fin_month") < keys.index("next_fin_month")


# ============================================================================
# Date operator override — has_date_filter + lookup semantics
# ============================================================================

class TestDateOperatorOverride:
    """
    Tests for has_date_filter and the ORM lookup semantics it enables.

    When a dashboard card's query contains a date comparison operator, the
    period queryset is replaced with an unfiltered one so the card's own
    date range overrides the global period filter. These tests verify:
      - which query strings trigger the override
      - which ORM lookups each operator produces
      - that gt/gte remove the period's lower bound (pre-period expenses allowed)
      - that lt/lte remove the period's upper bound (post-period expenses allowed)
    """

    # -- Detection -----------------------------------------------------------

    def test_gt_triggers_override(self):
        assert _has_date_filter("date>2024-01-01") is True

    def test_gte_triggers_override(self):
        assert _has_date_filter("date>=2024-01-01") is True

    def test_lt_triggers_override(self):
        assert _has_date_filter("date<2024-12-31") is True

    def test_lte_triggers_override(self):
        assert _has_date_filter("date<=2024-12-31") is True

    def test_eq_triggers_override(self):
        assert _has_date_filter("date==2024-06-15") is True

    def test_no_date_operator_no_override(self):
        assert _has_date_filter("type=expense cat=food") is False

    def test_bare_date_word_no_override(self):
        assert _has_date_filter("date") is False

    def test_date_in_free_text_no_override(self):
        assert _has_date_filter('"best date ever"') is False

    def test_empty_query_no_override(self):
        assert _has_date_filter("") is False

    def test_none_query_no_override(self):
        assert _has_date_filter(None) is False

    def test_combined_gt_lt_triggers_override(self):
        assert _has_date_filter("date>2024-01-01 date<2024-12-31") is True

    def test_date_operator_with_other_filters(self):
        assert _has_date_filter("type=expense date>=2024-01-01 cat=food") is True

    # -- ORM lookup semantics ------------------------------------------------

    def test_gt_produces_gt_lookup(self):
        assert _date_lookup(">") == "gt"

    def test_gte_produces_gte_lookup(self):
        assert _date_lookup(">=") == "gte"

    def test_lt_produces_lt_lookup(self):
        assert _date_lookup("<") == "lt"

    def test_lte_produces_lte_lookup(self):
        assert _date_lookup("<=") == "lte"

    def test_eq_produces_exact_lookup(self):
        assert _date_lookup("=") == "exact"

    def test_double_eq_produces_exact_lookup(self):
        assert _date_lookup("==") == "exact"

    # -- Semantic meaning: which bounds each operator removes ----------------

    def test_gt_removes_lower_bound(self):
        # date>X means: no lower bound set by the period; expenses from BEFORE
        # the period start (but after X) are included.
        # 'gt' (greater-than) only constrains the lower end: date_due > X.
        # There is no upper-bound constraint, so post-period dates are also included.
        lookup = _date_lookup(">")
        assert lookup == "gt"
        # Any date strictly after X satisfies date_due__gt=X
        X = date(2024, 1, 1)
        period_start = date(2026, 5, 27)
        pre_period = date(2025, 6, 1)   # before period_start, but after X
        assert pre_period > X           # would pass date_due__gt=X
        assert pre_period < period_start  # would NOT pass the period filter

    def test_gte_removes_lower_bound(self):
        lookup = _date_lookup(">=")
        assert lookup == "gte"
        X = date(2024, 1, 1)
        period_start = date(2026, 5, 27)
        pre_period = date(2024, 1, 1)   # exactly on X
        assert pre_period >= X
        assert pre_period < period_start

    def test_lt_removes_upper_bound(self):
        # date<X means: no upper bound set by the period; expenses from AFTER
        # the period end (but before X) are included.
        lookup = _date_lookup("<")
        assert lookup == "lt"
        X = date(2027, 1, 1)
        period_end = date(2026, 6, 26)
        post_period = date(2026, 12, 1)  # after period_end, but before X
        assert post_period < X           # would pass date_due__lt=X
        assert post_period > period_end  # would NOT pass the period filter

    def test_lte_removes_upper_bound(self):
        lookup = _date_lookup("<=")
        assert lookup == "lte"
        X = date(2027, 1, 1)
        period_end = date(2026, 6, 26)
        post_period = date(2027, 1, 1)
        assert post_period <= X
        assert post_period > period_end

    def test_exact_pins_to_single_date(self):
        # date==X means: only expenses on exactly X, regardless of period.
        # Both the lower and upper bounds of the period are overridden.
        lookup = _date_lookup("==")
        assert lookup == "exact"
        X = date(2020, 3, 15)
        period_start = date(2026, 5, 27)
        period_end   = date(2026, 6, 26)
        # X is outside the period entirely, yet date==X matches only X.
        assert X < period_start  # before period

    def test_combined_date_range_in_query_creates_own_window(self):
        # date>X date<Y: both lower and upper bounds come from the query,
        # not from the period. Expenses between X and Y are included even if
        # they fall entirely outside the current period.
        assert _has_date_filter("date>2020-01-01 date<2020-12-31") is True
        # The two operators override both the period start and period end.
        lower_lookup = _date_lookup(">")
        upper_lookup = _date_lookup("<")
        assert lower_lookup == "gt"   # removes period's lower bound
        assert upper_lookup == "lt"   # removes period's upper bound

    def test_only_gt_in_query_leaves_upper_bound_open(self):
        # date>X with no upper-bound operator: the override removes the period
        # entirely, so there is no upper date constraint from the query itself.
        # Expenses arbitrarily far in the future would match.
        assert _has_date_filter("date>2020-01-01") is True
        lookup = _date_lookup(">")
        assert lookup == "gt"
        # Without an upper-bound operator, only the lower bound is set.
        very_future = date(2099, 12, 31)
        X = date(2020, 1, 1)
        assert very_future > X  # would pass date_due__gt=X with no upper limit

    def test_only_lt_in_query_leaves_lower_bound_open(self):
        # date<X with no lower-bound operator: no lower date constraint.
        assert _has_date_filter("date<2030-01-01") is True
        lookup = _date_lookup("<")
        assert lookup == "lt"
        very_past = date(1900, 1, 1)
        X = date(2030, 1, 1)
        assert very_past < X  # would pass date_due__lt=X with no lower limit
