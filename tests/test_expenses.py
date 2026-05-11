"""Expense CRUD via browser, plus all-fields API round-trip and CSV export."""
import re
import time

import requests
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import (
    _url, BASE_URL, fill, submit, wait_url, wait_text, server_today,
    session_cookies, api_post, api_get, api_delete,
    setup_user, cleanup_user,
)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestExpenses:

    def test_create(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        fill(w, By.ID, "id_title", "E2E Expense")
        fill(w, By.ID, "id_value", "42.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;")
        submit(w)
        wait_url(w, "/budget/expenses/")
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "E2E Expense"})
        ctx["exp_uid"] = str(resp.json()["expenses"][0]["id"])

    def test_edit(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_uid']}/edit/"))
        fill(w, By.ID, "id_title", "E2E Expense Edited")
        submit(w)
        wait_url(w, "/budget/expenses/")
        time.sleep(2)

    def test_clone(self, driver, w, ctx):
        # Navigate to the edit page and use the clone form there is unavailable,
        # so POST directly via session to trigger clone, then land on clone's edit page.
        cookies = session_cookies(driver)
        csrf = cookies.get("csrftoken", "")
        r = requests.post(
            _url(f"/budget/expenses/{ctx['exp_uid']}/clone/"),
            cookies=cookies,
            headers={"X-CSRFToken": csrf, "Referer": BASE_URL + "/"},
            allow_redirects=False,
        )
        edit_url = r.headers.get("Location", "")
        if edit_url.startswith("/"):
            edit_url = BASE_URL + edit_url
        driver.get(edit_url)
        time.sleep(1)
        ctx["clone_uid"] = re.search(r'/expenses/(\d+)/edit/', driver.current_url).group(1)
        assert "CLONE - E2E Expense Edited" in driver.find_element(By.ID, "id_title").get_attribute("value")
        submit(w)
        wait_url(w, "/budget/expenses/")

    def test_delete_clone(self, driver, w, ctx):
        cookies = session_cookies(driver)
        csrf = cookies.get("csrftoken", "")
        requests.post(
            _url(f"/budget/expenses/{ctx['clone_uid']}/delete/"),
            cookies=cookies,
            headers={"X-CSRFToken": csrf, "Referer": BASE_URL + "/"},
            allow_redirects=False,
        )
        time.sleep(1)
        resp = api_get(f"/api/v1/expenses/{ctx['clone_uid']}/", ctx)
        assert resp.status_code == 404

    def test_all_fields_round_trip(self, driver, w, ctx):
        today = server_today()
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "E2E AllFields", "type": "expense", "value": "77.77",
            "payee": "Test Payee", "note": "Test note",
            "date_due": today, "settled": False, "auto_settle_on_due_date": True,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["payee"] == "Test Payee"
        assert data["note"] == "Test note"
        assert data["auto_settle_on_due_date"] is True
        r2 = api_get(f"/api/v1/expenses/{data['id']}/", ctx)
        assert r2.status_code == 200
        assert r2.json()["payee"] == "Test Payee"
        api_delete(f"/api/v1/expenses/{data['id']}/", ctx)

    def test_type_income(self, driver, w, ctx):
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "E2E Income", "type": "income", "value": "500.00",
            "date_due": server_today(), "settled": True,
        })
        assert resp.status_code == 201
        assert resp.json()["type"] == "income"
        ctx["income_id"] = resp.json()["id"]

    def test_type_savings(self, driver, w, ctx):
        today = server_today()
        dep = api_post("/api/v1/expenses/", ctx, json={
            "title": "E2E SavingsDep", "type": "savings_dep",
            "value": "200.00", "date_due": today, "settled": True,
        })
        assert dep.status_code == 201
        wit = api_post("/api/v1/expenses/", ctx, json={
            "title": "E2E SavingsWit", "type": "savings_wit",
            "value": "50.00", "date_due": today, "settled": True,
        })
        assert wit.status_code == 201
        ctx["dep_id"] = dep.json()["id"]
        ctx["wit_id"] = wit.json()["id"]

    def test_dashboard_totals(self, driver, w, ctx):
        dash = api_get("/api/v1/dashboard/", ctx)
        assert dash.status_code == 200
        data = dash.json()
        assert float(data["income"]) >= 500.0
        assert "expenses_paid" in data
        assert "balance" in data

    def test_csv_export(self, driver, w, ctx):
        cookies = session_cookies(driver)
        resp = requests.get(_url("/budget/expenses/export/"), cookies=cookies, timeout=10)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")
        assert "date_due,title,type,value" in resp.text
        assert "E2E Expense Edited" in resp.text

    def test_cleanup(self, driver, w, ctx):
        for key in ("income_id", "dep_id", "wit_id"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)
