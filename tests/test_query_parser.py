"""
Query parser feature tests via the REST API expense list endpoint.

Uses GET /api/v1/expenses/?q=QUERY&view=year&year=2025 to verify
date comparisons (all three formats), the 'today' keyword, value
comparisons, the NOT operator, multi-constraint tag filters, and
the deactivated= flag.  No browser interaction required.
"""
import pytest

from helpers import (
    api_get, api_post, api_patch, api_delete,
    server_today, setup_user, cleanup_user,
)

YEAR = 2025
PAST_ISO   = "2025-03-01"
MID_ISO    = "2025-06-15"
FUTURE_ISO = "2025-09-01"


def _api_titles(ctx, q, year=2025):
    params = {"q": q, "view": "year", "year": year}
    resp = api_get("/api/v1/expenses/", ctx, params=params)
    return [e["title"] for e in resp.json()["expenses"]]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)

    past = api_post("/api/v1/expenses/", c, json={
        "title": "QP Past", "type": "expense", "value": "10.00",
        "date_due": PAST_ISO, "settled": False,
    })
    assert past.status_code == 201
    c["qp_past"] = past.json()["id"]

    mid = api_post("/api/v1/expenses/", c, json={
        "title": "QP Mid", "type": "expense", "value": "20.00",
        "date_due": MID_ISO, "settled": False,
    })
    assert mid.status_code == 201
    c["qp_mid"] = mid.json()["id"]

    future = api_post("/api/v1/expenses/", c, json={
        "title": "QP Future", "type": "expense", "value": "30.00",
        "date_due": FUTURE_ISO, "settled": False,
    })
    assert future.status_code == 201
    c["qp_future"] = future.json()["id"]

    income = api_post("/api/v1/expenses/", c, json={
        "title": "QP Income", "type": "income", "value": "500.00",
        "date_due": MID_ISO, "settled": False,
    })
    assert income.status_code == 201
    c["qp_income"] = income.json()["id"]

    deact = api_post("/api/v1/expenses/", c, json={
        "title": "QP Deact", "type": "expense", "value": "99.00",
        "date_due": MID_ISO, "settled": False,
    })
    assert deact.status_code == 201
    c["qp_deact"] = deact.json()["id"]
    r = api_patch(f"/api/v1/expenses/{c['qp_deact']}/", c, json={"deactivated": True})
    assert r.status_code == 200

    yield c

    for key in ("qp_past", "qp_mid", "qp_future", "qp_income", "qp_deact"):
        if key in c:
            api_delete(f"/api/v1/expenses/{c[key]}/", c)
    cleanup_user(c["email"])


class TestDateFormats:

    # dd.mm.yyyy

    def test_dmy_gt(self, driver, w, ctx):
        t = _api_titles(ctx, "date>01.03.2025")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_dmy_gte(self, driver, w, ctx):
        t = _api_titles(ctx, "date>=15.06.2025")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_dmy_lt(self, driver, w, ctx):
        t = _api_titles(ctx, "date<01.09.2025")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_dmy_lte(self, driver, w, ctx):
        t = _api_titles(ctx, "date<=15.06.2025")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_dmy_eq(self, driver, w, ctx):
        t = _api_titles(ctx, "date=15.06.2025")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    def test_dmy_eqeq(self, driver, w, ctx):
        t = _api_titles(ctx, "date==15.06.2025")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    # mm/dd/yyyy

    def test_mdy_gt(self, driver, w, ctx):
        t = _api_titles(ctx, "date>03/01/2025")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_mdy_gte(self, driver, w, ctx):
        t = _api_titles(ctx, "date>=06/15/2025")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_mdy_lt(self, driver, w, ctx):
        t = _api_titles(ctx, "date<09/01/2025")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_mdy_lte(self, driver, w, ctx):
        t = _api_titles(ctx, "date<=06/15/2025")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_mdy_eq(self, driver, w, ctx):
        t = _api_titles(ctx, "date=06/15/2025")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    def test_mdy_eqeq(self, driver, w, ctx):
        t = _api_titles(ctx, "date==06/15/2025")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    # yyyy-mm-dd

    def test_iso_gt(self, driver, w, ctx):
        t = _api_titles(ctx, "date>2025-03-01")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_iso_gte(self, driver, w, ctx):
        t = _api_titles(ctx, "date>=2025-06-15")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_iso_lt(self, driver, w, ctx):
        t = _api_titles(ctx, "date<2025-09-01")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_iso_lte(self, driver, w, ctx):
        t = _api_titles(ctx, "date<=2025-06-15")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_iso_eq(self, driver, w, ctx):
        t = _api_titles(ctx, "date=2025-06-15")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    def test_iso_eqeq(self, driver, w, ctx):
        t = _api_titles(ctx, "date==2025-06-15")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t


class TestTodayKeyword:

    def test_setup_today(self, driver, w, ctx):
        today_iso = server_today()
        ctx["qp_today_iso"] = today_iso
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP Today", "type": "expense", "value": "5.00",
            "date_due": today_iso, "settled": False,
        })
        assert exp.status_code == 201
        ctx["qp_today_dyn"] = exp.json()["id"]

    def _titles_today(self, ctx, q):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": q, "view": "year"})
        return [e["title"] for e in resp.json()["expenses"]]

    def test_today_eq(self, driver, w, ctx):
        t = self._titles_today(ctx, "date=today")
        assert "QP Today" in t

    def test_today_eqeq(self, driver, w, ctx):
        t = self._titles_today(ctx, "date==today")
        assert "QP Today" in t

    def test_today_gt(self, driver, w, ctx):
        t = self._titles_today(ctx, "date>today")
        assert "QP Today" not in t

    def test_today_lt(self, driver, w, ctx):
        t = self._titles_today(ctx, "date<today")
        assert "QP Today" not in t

    def test_today_gte(self, driver, w, ctx):
        t = self._titles_today(ctx, "date>=today")
        assert "QP Today" in t

    def test_today_lte(self, driver, w, ctx):
        t = self._titles_today(ctx, "date<=today")
        assert "QP Today" in t

    def test_cleanup_today(self, driver, w, ctx):
        if "qp_today_dyn" in ctx:
            api_delete(f"/api/v1/expenses/{ctx.pop('qp_today_dyn')}/", ctx)
        ctx.pop("qp_today_iso", None)


class TestValueComparisons:

    def test_value_exclusive_range(self, driver, w, ctx):
        t = _api_titles(ctx, "value>10 value<30")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    def test_value_inclusive_range(self, driver, w, ctx):
        t = _api_titles(ctx, "value>=10 value<=20")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_value_not_range(self, driver, w, ctx):
        t = _api_titles(ctx, "value>=10 !value>=30")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t


class TestNotOperator:

    def test_not_term(self, driver, w, ctx):
        t = _api_titles(ctx, "type=expense !(QP Past)")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_not_filter(self, driver, w, ctx):
        t = _api_titles(ctx, "!type=income")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" in t
        assert "QP Income" not in t

    def test_not_group(self, driver, w, ctx):
        t = _api_titles(ctx, "!(type=income)")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" in t
        assert "QP Income" not in t

    def test_not_group_with_or(self, driver, w, ctx):
        t = _api_titles(ctx, "type=expense !(QP Past || QP Future)")
        assert "QP Mid" in t
        assert "QP Past" not in t and "QP Future" not in t


class TestMultipleConstraints:

    def test_setup_tags(self, driver, w, ctx):
        ta = api_post("/api/v1/tags/", ctx, json={"title": "qptaga"})
        assert ta.status_code == 201
        ctx["qp_tag_a"] = ta.json()["id"]

        tb = api_post("/api/v1/tags/", ctx, json={"title": "qptagb"})
        assert tb.status_code == 201
        ctx["qp_tag_b"] = tb.json()["id"]

        only_a = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP TagA", "type": "expense", "value": "1.00",
            "date_due": MID_ISO, "tag_ids": [ctx["qp_tag_a"]],
        })
        assert only_a.status_code == 201
        ctx["qp_only_a"] = only_a.json()["id"]

        only_b = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP TagB", "type": "expense", "value": "2.00",
            "date_due": MID_ISO, "tag_ids": [ctx["qp_tag_b"]],
        })
        assert only_b.status_code == 201
        ctx["qp_only_b"] = only_b.json()["id"]

        both = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP TagBoth", "type": "expense", "value": "3.00",
            "date_due": MID_ISO, "tag_ids": [ctx["qp_tag_a"], ctx["qp_tag_b"]],
        })
        assert both.status_code == 201
        ctx["qp_both"] = both.json()["id"]

    def test_tag_and(self, driver, w, ctx):
        t = _api_titles(ctx, "tag=qptaga tag=qptagb")
        assert "QP TagBoth" in t
        assert "QP TagA" not in t and "QP TagB" not in t

    def test_tag_not(self, driver, w, ctx):
        t = _api_titles(ctx, "tag=qptaga !tag=qptagb")
        assert "QP TagA" in t
        assert "QP TagBoth" not in t and "QP TagB" not in t

    def test_cleanup_tags(self, driver, w, ctx):
        for key in ("qp_only_a", "qp_only_b", "qp_both"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)
        for key in ("qp_tag_a", "qp_tag_b"):
            if key in ctx:
                api_delete(f"/api/v1/tags/{ctx.pop(key)}/", ctx)


class TestDeactivated:

    def test_deactivated_yes(self, driver, w, ctx):
        t = _api_titles(ctx, "deactivated=yes")
        assert "QP Deact" in t
        assert "QP Past" not in t and "QP Mid" not in t and "QP Future" not in t

    def test_deactivated_no(self, driver, w, ctx):
        t = _api_titles(ctx, "deactivated=no")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" in t
        assert "QP Deact" not in t


class TestWeekKeywords:

    def _titles(self, ctx, q):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": q, "view": "year"})
        return [e["title"] for e in resp.json()["expenses"]]

    def test_setup_week(self, driver, w, ctx):
        today_iso = server_today()
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP ThisWeek", "type": "expense", "value": "9.00",
            "date_due": today_iso, "settled": False,
        })
        assert exp.status_code == 201
        ctx["qp_this_week"] = exp.json()["id"]

    def test_cur_week_start_lte_today(self, driver, w, ctx):
        # cur_week_start is Monday; today >= Monday, so date>=cur_week_start must include today
        t = self._titles(ctx, "date>=cur_week_start")
        assert "QP ThisWeek" in t

    def test_cur_week_end_gte_today(self, driver, w, ctx):
        # cur_week_end is Sunday; today <= Sunday, so date<=cur_week_end must include today
        t = self._titles(ctx, "date<=cur_week_end")
        assert "QP ThisWeek" in t

    def test_cur_week_range_includes_today(self, driver, w, ctx):
        t = self._titles(ctx, "date>=cur_week_start date<=cur_week_end")
        assert "QP ThisWeek" in t

    def test_cur_week_range_excludes_past(self, driver, w, ctx):
        # PAST_ISO = 2025-03-01 which is well outside any current week
        t = self._titles(ctx, "date>=cur_week_start date<=cur_week_end")
        assert "QP Past" not in t

    def test_cur_week_start_excludes_before_week(self, driver, w, ctx):
        # date<cur_week_start must NOT include today (today is within the week)
        t = self._titles(ctx, "date<cur_week_start")
        assert "QP ThisWeek" not in t

    def test_cur_week_end_excludes_after_week(self, driver, w, ctx):
        # date>cur_week_end must NOT include today
        t = self._titles(ctx, "date>cur_week_end")
        assert "QP ThisWeek" not in t

    def test_cleanup_week(self, driver, w, ctx):
        if "qp_this_week" in ctx:
            api_delete(f"/api/v1/expenses/{ctx.pop('qp_this_week')}/", ctx)
