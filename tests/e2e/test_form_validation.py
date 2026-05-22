"""
Server-side form and JSON endpoint validation tests.

Uses the browser session cookies to authenticate a requests.Session,
then posts directly to form and JSON endpoints to verify that invalid
input returns 200 (form re-render) or 400 (JSON error) rather than
a redirect.
"""
import re
import requests
import pytest

from helpers import BASE_URL, session_cookies, setup_user, cleanup_user


LONG_128  = "x" * 129
LONG_1024 = "x" * 1025


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


def _session(driver):
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    if not s.cookies.get("csrftoken"):
        s.get(BASE_URL + "/budget/categories-tags/")
    return s


def _csrf(s):
    return s.cookies.get("csrftoken", "")


def _form_post(s, path, data):
    csrf = _csrf(s)
    return s.post(
        BASE_URL + path,
        data={"csrfmiddlewaretoken": csrf, **data},
        headers={"Referer": BASE_URL + "/"},
        allow_redirects=False,
    )


def _json_post(s, path, payload):
    csrf = _csrf(s)
    return s.post(
        BASE_URL + path,
        json=payload,
        headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        allow_redirects=False,
    )


BASE_EXPENSE = {
    "title": "Val",
    "type": "expense",
    "value": "1.00",
    "date_due": "2026-01-01",
    "settled": "1",
    "notify": "1",
}

BASE_SCHEDULED = {
    "title": "Val",
    "type": "expense",
    "value": "1.00",
    "repeat_every_factor": "1",
    "repeat_every_unit": "months",
    "repeat_base_date": "2026-01-01",
    "notify": "1",
}

BASE_PROFILE = {
    "action": "profile",
    "first_name": "Test",
    "last_name": "Test",
    "currency": "€",
    "month_start_day": "1",
    "unspent_allowance_action": "do_nothing",
}


class TestCategoryTagJsonEndpoints:

    def test_category_create_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _json_post(s, "/budget/categories/create/", {"title": LONG_128})
        assert resp.status_code == 400

    def test_category_rename_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        cat = _json_post(s, "/budget/categories/create/", {"title": "FVCat"}).json()
        resp = _json_post(s, f"/budget/categories/{cat['uid']}/rename/", {"title": LONG_128})
        assert resp.status_code == 400

    def test_tag_create_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _json_post(s, "/budget/tags/create/", {"title": LONG_128})
        assert resp.status_code == 400

    def test_tag_rename_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        tag = _json_post(s, "/budget/tags/create/", {"title": "FVTag"}).json()
        resp = _json_post(s, f"/budget/tags/{tag['uid']}/rename/", {"title": LONG_128})
        assert resp.status_code == 400


class TestExpenseFormValidation:

    def test_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**BASE_EXPENSE, "title": LONG_128})
        assert resp.status_code == 200

    def test_payee_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**BASE_EXPENSE, "payee": LONG_128})
        assert resp.status_code == 200

    def test_note_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**BASE_EXPENSE, "note": LONG_1024})
        assert resp.status_code == 200

    def test_invalid_type(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**BASE_EXPENSE, "type": "carry_over"})
        assert resp.status_code == 200


class TestScheduledFormValidation:

    def test_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**BASE_SCHEDULED, "title": LONG_128})
        assert resp.status_code == 200

    def test_payee_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**BASE_SCHEDULED, "payee": LONG_128})
        assert resp.status_code == 200

    def test_note_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**BASE_SCHEDULED, "note": LONG_1024})
        assert resp.status_code == 200

    def test_invalid_type(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**BASE_SCHEDULED, "type": "carry_over"})
        assert resp.status_code == 200

    def test_repeat_factor_missing(self, driver, w, ctx):
        s = _session(driver)
        data = {k: v for k, v in BASE_SCHEDULED.items() if k != "repeat_every_factor"}
        resp = _form_post(s, "/budget/scheduled/new/", data)
        assert resp.status_code == 200

    def test_repeat_unit_missing(self, driver, w, ctx):
        s = _session(driver)
        data = {k: v for k, v in BASE_SCHEDULED.items() if k != "repeat_every_unit"}
        resp = _form_post(s, "/budget/scheduled/new/", data)
        assert resp.status_code == 200


class TestProfileFormValidation:

    def test_first_name_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {**BASE_PROFILE, "first_name": LONG_128})
        assert resp.status_code == 200

    def test_last_name_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {**BASE_PROFILE, "last_name": LONG_128})
        assert resp.status_code == 200

    def test_month_start_day_out_of_range(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {**BASE_PROFILE, "month_start_day": "99"})
        assert resp.status_code == 200

    def test_invalid_allowance_action(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {**BASE_PROFILE, "unspent_allowance_action": "invalid_action"})
        assert resp.status_code == 200
