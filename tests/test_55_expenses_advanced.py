"""
Detailed expense field validation, dashboard totals, list view, and CSV export.
Requires the API key set up in test_50_profile.py.
"""
from datetime import date

import requests
from selenium.webdriver.common.by import By

from conftest import (
    _url, wait_text,
    api_post, api_get, api_delete, session_cookies,
)


class TestExpensesAdvanced:

    def test_53_expense_all_fields_stored(self, driver, w, ctx):
        """Create expense with every field set; verify all values round-trip correctly."""
        today = date.today().isoformat()
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "Full Field Expense",
            "type": "expense",
            "value": "77.77",
            "payee": "Test Payee",
            "note": "Test note content",
            "date_due": today,
            "settled": False,
            "auto_settle_on_due_date": True,
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["title"] == "Full Field Expense"
        assert data["type"] == "expense"
        assert data["value"] == "77.77"
        assert data["payee"] == "Test Payee"
        assert data["note"] == "Test note content"
        assert data["date_due"] == today
        assert data["settled"] is False
        assert data["auto_settle_on_due_date"] is True
        ctx["full_field_expense_id"] = data["id"]

        resp2 = api_get(f"/api/v1/expenses/{data['id']}/", ctx)
        assert resp2.status_code == 200
        d2 = resp2.json()
        assert d2["payee"] == "Test Payee"
        assert d2["note"] == "Test note content"
        assert d2["auto_settle_on_due_date"] is True

    def test_54_income_expense_type(self, driver, w, ctx):
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "Income Entry",
            "type": "income",
            "value": "500.00",
            "date_due": date.today().isoformat(),
            "settled": True,
        })
        assert resp.status_code == 201
        assert resp.json()["type"] == "income"
        ctx["income_expense_id"] = resp.json()["id"]

    def test_55_savings_deposit_and_withdrawal(self, driver, w, ctx):
        today = date.today().isoformat()
        dep = api_post("/api/v1/expenses/", ctx, json={
            "title": "Savings Deposit",
            "type": "savings_dep",
            "value": "200.00",
            "date_due": today,
            "settled": True,
        })
        assert dep.status_code == 201
        assert dep.json()["type"] == "savings_dep"
        ctx["savings_dep_id"] = dep.json()["id"]

        wit = api_post("/api/v1/expenses/", ctx, json={
            "title": "Savings Withdrawal",
            "type": "savings_wit",
            "value": "50.00",
            "date_due": today,
            "settled": True,
        })
        assert wit.status_code == 201
        assert wit.json()["type"] == "savings_wit"
        ctx["savings_wit_id"] = wit.json()["id"]

    def test_56_dashboard_totals_reflect_expenses(self, driver, w, ctx):
        resp = api_get("/api/v1/dashboard/", ctx)
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["income"]) >= 500.0
        assert float(data["expenses_paid"]) >= 42.0

    def test_57_expense_list_view_shows_correct_entries(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, "Selenium Expense Edited")
        wait_text(driver, w, "Full Field Expense")
        wait_text(driver, w, "Income Entry")

    def test_58_expenses_csv_export(self, driver, w, ctx):
        cookies = session_cookies(driver)
        resp = requests.get(_url("/budget/expenses/export/"), cookies=cookies, timeout=10)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")
        assert "Content-Disposition" in resp.headers
        text = resp.text
        assert "date_due,title,type,value" in text
        assert "Selenium Expense Edited" in text

    def test_59_cleanup_extra_expenses(self, driver, w, ctx):
        for key in ("full_field_expense_id", "income_expense_id", "savings_dep_id", "savings_wit_id"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx[key]}/", ctx)
