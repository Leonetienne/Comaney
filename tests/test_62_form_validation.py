"""Server-side form and JSON-endpoint validation tests.

Uses the live browser session so we don't have to replicate login flow.
"""
import re
import requests
from conftest import BASE_URL


LONG_128  = "x" * 129
LONG_1024 = "x" * 1025


def _session(driver):
    """Return a requests.Session authenticated with the Selenium browser's cookies."""
    s = requests.Session()
    for cookie in driver.get_cookies():
        s.cookies.set(cookie["name"], cookie["value"])
    # Ensure csrftoken cookie is populated
    if not s.cookies.get("csrftoken"):
        s.get(BASE_URL + "/budget/categories-tags/")
    return s


def _csrf(session, path):
    """Fetch a page and return its csrfmiddlewaretoken."""
    resp = session.get(BASE_URL + path)
    match = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', resp.text)
    assert match, f"No CSRF token found on {path}"
    return match.group(1)


def _form_post(session, path, data, csrf_path=None):
    csrf = _csrf(session, csrf_path or path)
    return session.post(
        BASE_URL + path,
        data={"csrfmiddlewaretoken": csrf, **data},
        allow_redirects=False,
    )


def _json_post(session, path, payload):
    csrf = session.cookies.get("csrftoken", "")
    return session.post(
        BASE_URL + path,
        json=payload,
        headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        allow_redirects=False,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

_EXPENSE_BASE = {
    "title": "Val",
    "type": "expense",
    "value": "1.00",
    "date_due": "2026-01-01",
    "settled": "1",
    "notify": "1",
}

_SCHEDULED_BASE = {
    "title": "Val",
    "type": "expense",
    "value": "1.00",
    "repeat_every_factor": "1",
    "repeat_every_unit": "months",
    "repeat_base_date": "2026-01-01",
    "notify": "1",
}


class TestFormValidation:

    # ── Category / Tag JSON endpoints (budget views, not REST API) ────────────

    def test_f01_category_create_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _json_post(s, "/budget/categories/create/", {"title": LONG_128})
        assert resp.status_code == 400

    def test_f02_category_rename_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        cat = _json_post(s, "/budget/categories/create/", {"title": "FVCat"}).json()
        resp = _json_post(s, f"/budget/categories/{cat['uid']}/rename/", {"title": LONG_128})
        assert resp.status_code == 400

    def test_f03_tag_create_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _json_post(s, "/budget/tags/create/", {"title": LONG_128})
        assert resp.status_code == 400

    def test_f04_tag_rename_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        tag = _json_post(s, "/budget/tags/create/", {"title": "FVTag"}).json()
        resp = _json_post(s, f"/budget/tags/{tag['uid']}/rename/", {"title": LONG_128})
        assert resp.status_code == 400

    # ── Expense form ──────────────────────────────────────────────────────────

    def test_f05_expense_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**_EXPENSE_BASE, "title": LONG_128})
        assert resp.status_code == 200  # re-renders form with errors, not redirect

    def test_f06_expense_payee_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**_EXPENSE_BASE, "payee": LONG_128})
        assert resp.status_code == 200

    def test_f07_expense_note_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**_EXPENSE_BASE, "note": LONG_1024})
        assert resp.status_code == 200

    def test_f08_expense_invalid_type(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**_EXPENSE_BASE, "type": "carry_over"})
        assert resp.status_code == 200

    # ── Scheduled expense form ────────────────────────────────────────────────

    def test_f09_scheduled_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**_SCHEDULED_BASE, "title": LONG_128})
        assert resp.status_code == 200

    def test_f10_scheduled_payee_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**_SCHEDULED_BASE, "payee": LONG_128})
        assert resp.status_code == 200

    def test_f11_scheduled_note_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**_SCHEDULED_BASE, "note": LONG_1024})
        assert resp.status_code == 200

    def test_f12_scheduled_invalid_type(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**_SCHEDULED_BASE, "type": "carry_over"})
        assert resp.status_code == 200

    # ── Profile form ──────────────────────────────────────────────────────────

    def test_f13_profile_first_name_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {
            "action": "profile", "first_name": LONG_128, "last_name": "Test",
            "currency": "€", "month_start_day": "1",
            "unspent_allowance_action": "do_nothing",
        })
        assert resp.status_code == 200

    def test_f14_profile_last_name_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {
            "action": "profile", "first_name": "Test", "last_name": LONG_128,
            "currency": "€", "month_start_day": "1",
            "unspent_allowance_action": "do_nothing",
        })
        assert resp.status_code == 200

    def test_f15_profile_month_start_day_out_of_range(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {
            "action": "profile", "first_name": "Test", "last_name": "Test",
            "currency": "€", "month_start_day": "99",
            "unspent_allowance_action": "do_nothing",
        })
        assert resp.status_code == 200

    def test_f16_profile_invalid_allowance_action(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {
            "action": "profile", "first_name": "Test", "last_name": "Test",
            "currency": "€", "month_start_day": "1",
            "unspent_allowance_action": "drop_it_like_its_hot",
        })
        assert resp.status_code == 200
