"""
Advanced query-parser features: due_date comparisons, deactivated= filter, NOT operator.

Tests:
  - due_date= / due_date> / due_date>= / due_date< / due_date<= / due_date==
    with all three formats: dd.mm.yyyy, mm/dd/yyyy, yyyy-mm-dd
  - deactivated=yes / deactivated=no
  - !term   (NOT negates a single atom)
  - !(group) (NOT negates a parenthesised expression)

All date-comparison tests use a fixed reference year (FIXED_YEAR) and three
hard-coded dates spread across that year.  The expense-list view is always
pinned to view=year&year=FIXED_YEAR so results are never clipped by a
month boundary, and the tests are fully deterministic regardless of when
they run.
"""
import time
from datetime import date
from urllib.parse import urlencode

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from conftest import (
    _url, api_post, api_patch, api_delete, CLICK_PACE,
)


# ---------------------------------------------------------------------------
# Fixed reference dates — hard-coded, immune to month/year boundary issues
# ---------------------------------------------------------------------------

FIXED_YEAR = 2025

_PAST_D   = date(2025, 3, 1)    # early in the year
_MID_D    = date(2025, 6, 15)   # mid-year  (the "equals" target)
_FUTURE_D = date(2025, 9, 1)    # late in the year

PAST_ISO   = _PAST_D.isoformat()   # "2025-03-01"
MID_ISO    = _MID_D.isoformat()    # "2025-06-15"
FUTURE_ISO = _FUTURE_D.isoformat() # "2025-09-01"


def _dmy(d: date) -> str:
    """dd.mm.yyyy"""
    return f"{d.day:02d}.{d.month:02d}.{d.year}"

def _mdy(d: date) -> str:
    """mm/dd/yyyy"""
    return f"{d.month:02d}/{d.day:02d}/{d.year}"

def _iso(d: date) -> str:
    """yyyy-mm-dd"""
    return d.isoformat()


# ---------------------------------------------------------------------------
# Title constants
# ---------------------------------------------------------------------------

TITLE_PAST      = "QP86 Past Expense"
TITLE_TODAY     = "QP86 Today Expense"
TITLE_FUTURE    = "QP86 Future Expense"
TITLE_INCOME    = "QP86 Income Entry"
TITLE_DEACT     = "QP86 Deactivated"
TITLE_TODAY_DYN = "QP86 TodayConst"   # expense created with actual server today

# Multi-constraint tag test titles
TITLE_TAG_ONLY_A  = "QP86 TagOnlyA"   # has tag A only
TITLE_TAG_ONLY_B  = "QP86 TagOnlyB"   # has tag B only
TITLE_TAG_BOTH    = "QP86 TagBoth"    # has both tags A and B
TAG_SLUG_A = "qp86taga"
TAG_SLUG_B = "qp86tagb"


def _wait_settled(driver, timeout=4.0):
    WebDriverWait(driver, timeout).until(
        lambda d: (
            not d.find_element(By.ID, 'exp-list').get_attribute('data-search-pending') and
            not d.find_element(By.ID, 'exp-list').get_attribute('data-search-loading')
        )
    )


def search_type(driver, value):
    el = driver.find_element(By.ID, "exp-search")
    driver.execute_script(
        "arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
        el, value,
    )
    _wait_settled(driver)
    time.sleep(1)


def visible_titles(driver):
    cards = driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card")
    return [
        c.find_element(By.CSS_SELECTOR, ".exp-title").text
        for c in cards
        if c.value_of_css_property("display") != "none"
    ]


def url_search(driver, w, query):
    """Navigate to the expenses list pinned to FIXED_YEAR with ?search=."""
    driver.execute_script("sessionStorage.removeItem('expSearch')")
    driver.get(_url("/budget/expenses/") + "?" + urlencode({
        "search": query,
        "view":   "year",
        "year":   FIXED_YEAR,
    }))
    _wait_settled(driver)
    time.sleep(1)


class TestQueryParserAdvanced:

    # ── Setup ────────────────────────────────────────────────────────────────

    def test_86_00_setup(self, driver, w, ctx):
        past = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_PAST, "type": "expense", "value": "10.00",
            "date_due": PAST_ISO, "settled": False,
        })
        assert past.status_code == 201
        ctx["s86_past"] = past.json()["id"]

        today = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_TODAY, "type": "expense", "value": "20.00",
            "date_due": MID_ISO, "settled": False,
        })
        assert today.status_code == 201
        ctx["s86_today"] = today.json()["id"]

        future = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_FUTURE, "type": "expense", "value": "30.00",
            "date_due": FUTURE_ISO, "settled": False,
        })
        assert future.status_code == 201
        ctx["s86_future"] = future.json()["id"]

        income = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_INCOME, "type": "income", "value": "500.00",
            "date_due": MID_ISO, "settled": False,
        })
        assert income.status_code == 201
        ctx["s86_income"] = income.json()["id"]

        deact = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_DEACT, "type": "expense", "value": "99.00",
            "date_due": MID_ISO, "settled": False,
        })
        assert deact.status_code == 201
        ctx["s86_deact"] = deact.json()["id"]
        # Mark it deactivated
        r = api_patch(f"/api/v1/expenses/{ctx['s86_deact']}/", ctx,
                      json={"deactivated": True})
        assert r.status_code == 200

    # ── due_date comparisons — dd.mm.yyyy format ─────────────────────────────

    def test_86_10_due_date_gt_past_dmy(self, driver, w, ctx):
        """due_date>past shows today and future, not past."""
        url_search(driver, w, f"due_date>{_dmy(_PAST_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)

    def test_86_11_due_date_gte_today_dmy(self, driver, w, ctx):
        """due_date>=today shows today and future, not past."""
        url_search(driver, w, f"due_date>={_dmy(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)

    def test_86_12_due_date_lt_future_dmy(self, driver, w, ctx):
        """due_date<future shows past and today."""
        url_search(driver, w, f"due_date<{_dmy(_FUTURE_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_13_due_date_lte_today_dmy(self, driver, w, ctx):
        """due_date<=today shows past and today, not future."""
        url_search(driver, w, f"due_date<={_dmy(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_14_due_date_eq_today_dmy(self, driver, w, ctx):
        """due_date=today (single equals) shows only today."""
        url_search(driver, w, f"due_date={_dmy(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_15_due_date_eqeq_today_dmy(self, driver, w, ctx):
        """due_date==today (double equals) shows only today."""
        url_search(driver, w, f"due_date=={_dmy(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    # ── due_date comparisons — mm/dd/yyyy format ─────────────────────────────

    def test_86_20_due_date_gt_past_mdy(self, driver, w, ctx):
        """due_date>past (slash format) shows today and future."""
        url_search(driver, w, f"due_date>{_mdy(_PAST_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)

    def test_86_21_due_date_gte_today_mdy(self, driver, w, ctx):
        """due_date>=today (slash format) shows today and future, not past."""
        url_search(driver, w, f"due_date>={_mdy(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)

    def test_86_22_due_date_lt_future_mdy(self, driver, w, ctx):
        """due_date<future (slash format) shows past and today."""
        url_search(driver, w, f"due_date<{_mdy(_FUTURE_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_23_due_date_lte_today_mdy(self, driver, w, ctx):
        """due_date<=today (slash format) shows past and today."""
        url_search(driver, w, f"due_date<={_mdy(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_24_due_date_eq_today_mdy(self, driver, w, ctx):
        """due_date=today (slash format, single equals) shows only today."""
        url_search(driver, w, f"due_date={_mdy(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_25_due_date_eqeq_today_mdy(self, driver, w, ctx):
        """due_date==today (slash format, double equals) shows only today."""
        url_search(driver, w, f"due_date=={_mdy(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    # ── due_date comparisons — yyyy-mm-dd format ─────────────────────────────

    def test_86_26_due_date_gt_past_iso(self, driver, w, ctx):
        """due_date>past (ISO format) shows today and future."""
        url_search(driver, w, f"due_date>{_iso(_PAST_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)

    def test_86_27_due_date_gte_today_iso(self, driver, w, ctx):
        """due_date>=today (ISO format) shows today and future, not past."""
        url_search(driver, w, f"due_date>={_iso(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)

    def test_86_28_due_date_lt_future_iso(self, driver, w, ctx):
        """due_date<future (ISO format) shows past and today."""
        url_search(driver, w, f"due_date<{_iso(_FUTURE_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_29_due_date_lte_today_iso(self, driver, w, ctx):
        """due_date<=today (ISO format) shows past and today, not future."""
        url_search(driver, w, f"due_date<={_iso(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_2a_due_date_eq_today_iso(self, driver, w, ctx):
        """due_date=today (ISO format, single equals via kv path) shows only today."""
        url_search(driver, w, f"due_date={_iso(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_2b_due_date_eqeq_today_iso(self, driver, w, ctx):
        """due_date==today (ISO format, double equals) shows only today."""
        url_search(driver, w, f"due_date=={_iso(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    # ── deactivated= filter ──────────────────────────────────────────────────

    def test_86_30_deactivated_yes(self, driver, w, ctx):
        """deactivated=yes shows only the deactivated expense."""
        url_search(driver, w, "deactivated=yes")
        titles = visible_titles(driver)
        assert any(TITLE_DEACT in t for t in titles)
        assert not any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_31_deactivated_no(self, driver, w, ctx):
        """deactivated=no shows active expenses, not the deactivated one."""
        url_search(driver, w, "deactivated=no")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_DEACT in t for t in titles)

    # ── NOT operator: !term ──────────────────────────────────────────────────

    def test_86_40_not_term(self, driver, w, ctx):
        """type=expense !past hides expenses whose title contains 'past'."""
        url_search(driver, w, "type=expense !past")
        titles = visible_titles(driver)
        # Today and Future are expenses without 'past' in name → visible
        assert any(TITLE_TODAY in t for t in titles)
        assert any(TITLE_FUTURE in t for t in titles)
        # Past expense title contains 'past' → hidden
        assert not any(TITLE_PAST in t for t in titles)

    def test_86_41_not_filter(self, driver, w, ctx):
        """!type=income hides income entries, shows expenses."""
        url_search(driver, w, "!type=income")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_INCOME in t for t in titles)

    def test_86_42_not_combined(self, driver, w, ctx):
        """type=expense !settled=yes filters expenses that are not settled."""
        url_search(driver, w, "type=expense !settled=yes")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_INCOME in t for t in titles)

    # ── NOT operator: !(group) ────────────────────────────────────────────────

    def test_86_50_not_group(self, driver, w, ctx):
        """!(type=income) hides income — same as !type=income."""
        url_search(driver, w, "!(type=income)")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_INCOME in t for t in titles)

    def test_86_51_not_group_with_or(self, driver, w, ctx):
        """type=expense !(past || future) shows only today's expense."""
        url_search(driver, w, "type=expense !(past || future)")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_INCOME in t for t in titles)

    def test_86_52_not_group_filter_combo(self, driver, w, ctx):
        """!(type=income || type=expense) shows nothing from our test set (all are income/expense)."""
        url_search(driver, w, "!(type=income || type=expense)")
        titles = visible_titles(driver)
        assert not any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_INCOME in t for t in titles)

    # ── Combined: due_date + NOT ─────────────────────────────────────────────

    def test_86_60_due_date_and_not(self, driver, w, ctx):
        """due_date>=today !future shows only today."""
        url_search(driver, w, f"due_date>={_dmy(_MID_D)} !future")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)

    # ── 'today' constant ─────────────────────────────────────────────────────
    #
    # These tests use a separate expense whose date_due is the actual server
    # date, fetched inside the test body (not at module level).  The URL is
    # pinned to view=year (current financial year) so the expense is always
    # in range, regardless of which fixed year the other tests use.

    def test_86_70_setup_today_const(self, driver, w, ctx):
        """Create an expense due on the actual server today for 'today' tests."""
        from conftest import server_today
        ctx["s86_today_iso"] = server_today()
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_TODAY_DYN, "type": "expense", "value": "11.00",
            "date_due": ctx["s86_today_iso"], "settled": False,
        })
        assert exp.status_code == 201
        ctx["s86_today_dyn"] = exp.json()["id"]

    def _url_today(self, driver, w, query):
        """Search pinned to the current financial year (no fixed year)."""
        driver.execute_script("sessionStorage.removeItem('expSearch')")
        driver.get(_url("/budget/expenses/") + "?" + urlencode({
            "search": query,
            "view":   "year",
        }))
        _wait_settled(driver)
        import time; time.sleep(1)

    def test_86_71_due_date_eq_today(self, driver, w, ctx):
        """due_date=today (kv path) shows the today expense."""
        self._url_today(driver, w, "due_date=today")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY_DYN in t for t in titles)

    def test_86_72_due_date_eqeq_today(self, driver, w, ctx):
        """due_date==today (cmp path) shows the today expense."""
        self._url_today(driver, w, "due_date==today")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY_DYN in t for t in titles)

    def test_86_73_due_date_gt_today(self, driver, w, ctx):
        """due_date>today does NOT show the today expense."""
        self._url_today(driver, w, "due_date>today")
        titles = visible_titles(driver)
        assert not any(TITLE_TODAY_DYN in t for t in titles)

    def test_86_74_due_date_lt_today(self, driver, w, ctx):
        """due_date<today does NOT show the today expense."""
        self._url_today(driver, w, "due_date<today")
        titles = visible_titles(driver)
        assert not any(TITLE_TODAY_DYN in t for t in titles)

    def test_86_75_due_date_gte_today(self, driver, w, ctx):
        """due_date>=today shows the today expense."""
        self._url_today(driver, w, "due_date>=today")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY_DYN in t for t in titles)

    def test_86_76_due_date_lte_today(self, driver, w, ctx):
        """due_date<=today shows the today expense."""
        self._url_today(driver, w, "due_date<=today")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY_DYN in t for t in titles)

    def test_86_79_cleanup_today_const(self, driver, w, ctx):
        if "s86_today_dyn" in ctx:
            api_delete(f"/api/v1/expenses/{ctx.pop('s86_today_dyn')}/", ctx)
        ctx.pop("s86_today_iso", None)
        driver.execute_script("sessionStorage.removeItem('expSearch')")

    # ── Multiple constraints of the same type ────────────────────────────────
    #
    # Covers the general pattern where the same filter key appears more than
    # once in a query.  Each sub-category (value, date, tag) is tested for:
    #   - AND  (both constraints must hold simultaneously)
    #   - NOT  (second constraint negates a subset of the first)
    #
    # The tag sub-tests also serve as a regression guard for the Django M2M
    # multi-value JOIN bug fixed via the pk-in subquery approach.

    def test_86_80_setup_multi_constraint(self, driver, w, ctx):
        """Create two tags and three expenses for multi-constraint tests."""
        ta = api_post("/api/v1/tags/", ctx, json={"title": TAG_SLUG_A})
        assert ta.status_code == 201
        ctx["s86_tag_a"] = ta.json()["id"]

        tb = api_post("/api/v1/tags/", ctx, json={"title": TAG_SLUG_B})
        assert tb.status_code == 201
        ctx["s86_tag_b"] = tb.json()["id"]

        only_a = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_TAG_ONLY_A, "type": "expense", "value": "1.00",
            "date_due": MID_ISO, "tag_ids": [ctx["s86_tag_a"]],
        })
        assert only_a.status_code == 201
        ctx["s86_only_a"] = only_a.json()["id"]

        only_b = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_TAG_ONLY_B, "type": "expense", "value": "2.00",
            "date_due": MID_ISO, "tag_ids": [ctx["s86_tag_b"]],
        })
        assert only_b.status_code == 201
        ctx["s86_only_b"] = only_b.json()["id"]

        both = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_TAG_BOTH, "type": "expense", "value": "3.00",
            "date_due": MID_ISO, "tag_ids": [ctx["s86_tag_a"], ctx["s86_tag_b"]],
        })
        assert both.status_code == 201
        ctx["s86_both"] = both.json()["id"]

    # value — two comparisons (range)

    def test_86_81_value_range_exclusive(self, driver, w, ctx):
        """value>10 value<30: exclusive range matches only the mid expense (value=20)."""
        url_search(driver, w, "value>10 value<30")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)       # 20 → in range
        assert not any(TITLE_PAST in t for t in titles)    # 10 → not > 10
        assert not any(TITLE_FUTURE in t for t in titles)  # 30 → not < 30

    def test_86_82_value_range_inclusive(self, driver, w, ctx):
        """value>=10 value<=20: inclusive range matches past (10) and mid (20)."""
        url_search(driver, w, "value>=10 value<=20")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)        # 10 → in range
        assert any(TITLE_TODAY in t for t in titles)       # 20 → in range
        assert not any(TITLE_FUTURE in t for t in titles)  # 30 → out of range

    def test_86_83_value_not_range(self, driver, w, ctx):
        """value>=10 !value>=30: >=10 but NOT >=30 means 10 and 20 match, not 30."""
        url_search(driver, w, "value>=10 !value>=30")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    # due_date — two comparisons (date range)

    def test_86_84_date_range_exclusive(self, driver, w, ctx):
        """due_date>PAST due_date<FUTURE: exclusive range matches only mid."""
        url_search(driver, w, f"due_date>{_iso(_PAST_D)} due_date<{_iso(_FUTURE_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_PAST in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_85_date_range_inclusive(self, driver, w, ctx):
        """due_date>=PAST due_date<=MID: inclusive range matches past and mid."""
        url_search(driver, w, f"due_date>={_iso(_PAST_D)} due_date<={_iso(_MID_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    def test_86_86_date_not_range(self, driver, w, ctx):
        """due_date>=PAST !due_date>=FUTURE: open-ended lower bound excluding future."""
        url_search(driver, w, f"due_date>={_iso(_PAST_D)} !due_date>={_iso(_FUTURE_D)}")
        titles = visible_titles(driver)
        assert any(TITLE_PAST in t for t in titles)
        assert any(TITLE_TODAY in t for t in titles)
        assert not any(TITLE_FUTURE in t for t in titles)

    # tag — two conditions (M2M correctness)

    def test_86_87_tag_and(self, driver, w, ctx):
        """tag=A tag=B: only the expense with BOTH tags is shown."""
        url_search(driver, w, f"tag={TAG_SLUG_A} tag={TAG_SLUG_B}")
        titles = visible_titles(driver)
        assert any(TITLE_TAG_BOTH in t for t in titles)
        assert not any(TITLE_TAG_ONLY_A in t for t in titles)
        assert not any(TITLE_TAG_ONLY_B in t for t in titles)

    def test_86_88_tag_not(self, driver, w, ctx):
        """tag=A !tag=B: A-tagged expenses that do NOT also carry B."""
        url_search(driver, w, f"tag={TAG_SLUG_A} !tag={TAG_SLUG_B}")
        titles = visible_titles(driver)
        assert any(TITLE_TAG_ONLY_A in t for t in titles)
        assert not any(TITLE_TAG_BOTH in t for t in titles)
        assert not any(TITLE_TAG_ONLY_B in t for t in titles)

    def test_86_89_cleanup_multi_constraint(self, driver, w, ctx):
        for key in ("s86_only_a", "s86_only_b", "s86_both"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)
        for key in ("s86_tag_a", "s86_tag_b"):
            if key in ctx:
                api_delete(f"/api/v1/tags/{ctx.pop(key)}/", ctx)
        driver.execute_script("sessionStorage.removeItem('expSearch')")

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def test_86_99_cleanup(self, driver, w, ctx):
        for key in ("s86_past", "s86_today", "s86_future", "s86_income", "s86_deact"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)
        driver.execute_script("sessionStorage.removeItem('expSearch')")
