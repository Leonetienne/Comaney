"""
Regression tests for TICKET-01 — out-of-range `year` query param crashes views.

Several authenticated endpoints accept `year` (and `month`) from the query string
and hand them to datetime.date(...) without bounding to Python's valid year range
(1-9999). A `year` of 10000+ (or year=1 for a financial month that starts in the
previous calendar month) raises an unhandled ValueError -> HTTP 500, i.e. an
authenticated denial of service.

These tests hit the real endpoints and assert they no longer return 500.

EXPECTED TO FAIL until the parse helpers clamp the year: today
`GET /api/v1/expenses/?view=year&year=10000` and friends return 500.

Run with (live stack at :8080 required):
    pytest tests/e2e/api/test_year_param_crash.py -sxv | tee logfile.log
"""
import pytest
import requests

from helpers import (
    api_get, setup_user, cleanup_user, session_cookies, _url,
)

CRASH_YEARS = ["10000", "999999999", "0", "1"]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)  # also logs the browser in (for session-auth endpoints)
    yield c
    cleanup_user(c["email"])


class TestApiYearParam:
    """Bearer-token API: api/utils._parse_month feeds year into the range helpers."""

    @pytest.mark.parametrize("year", CRASH_YEARS)
    def test_expenses_year_view_no_500(self, driver, w, ctx, year):
        resp = api_get("/api/v1/expenses/", ctx, params={"view": "year", "year": year})
        assert resp.status_code != 500, \
            f"/api/v1/expenses/ crashed (500) for year={year}"
        assert resp.status_code == 200

    @pytest.mark.parametrize("year", CRASH_YEARS)
    def test_expenses_month_view_no_500(self, driver, w, ctx, year):
        resp = api_get("/api/v1/expenses/", ctx, params={"year": year, "month": "1"})
        assert resp.status_code != 500, \
            f"/api/v1/expenses/ crashed (500) for year={year}&month=1"
        assert resp.status_code == 200

    @pytest.mark.parametrize("year", CRASH_YEARS)
    def test_dashboard_year_no_500(self, driver, w, ctx, year):
        resp = api_get("/api/v1/dashboard/", ctx, params={"year": year, "month": "1"})
        assert resp.status_code != 500, \
            f"/api/v1/dashboard/ crashed (500) for year={year}"
        assert resp.status_code == 200


class TestSessionYearParam:
    """Session-auth endpoints: budget/views/_period._get_year / _get_month."""

    def _cookies(self, driver):
        return session_cookies(driver)

    @pytest.mark.parametrize("year", CRASH_YEARS)
    def test_dashboard_cards_year_view_no_500(self, driver, w, ctx, year):
        resp = requests.get(
            _url("/budget/dashboard/cards/"),
            params={"view": "year", "year": year},
            cookies=self._cookies(driver), timeout=10,
        )
        assert resp.status_code != 500, \
            f"/budget/dashboard/cards/ crashed (500) for year={year}"

    @pytest.mark.parametrize("year", CRASH_YEARS)
    def test_expenses_export_year_view_no_500(self, driver, w, ctx, year):
        resp = requests.get(
            _url("/budget/expenses/export/"),
            params={"view": "year", "year": year},
            cookies=self._cookies(driver), timeout=10,
        )
        assert resp.status_code != 500, \
            f"/budget/expenses/export/ crashed (500) for year={year}"
