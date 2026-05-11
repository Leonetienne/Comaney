"""Expense CRUD via browser, plus all-fields browser round-trip and CSV export."""
import re
import time

import requests
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import (
    _url, fill, submit, server_today,
    session_cookies, api_get, api_delete,
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
        time.sleep(2)
        assert "/budget/expenses/" in driver.current_url
        assert "E2E Expense" in driver.page_source
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "E2E Expense"})
        ctx["exp_uid"] = str(resp.json()["expenses"][0]["id"])

    def test_edit(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_uid']}/edit/"))
        fill(w, By.ID, "id_title", "E2E Expense Edited")
        submit(w)
        time.sleep(2)
        assert "/budget/expenses/" in driver.current_url
        assert "E2E Expense Edited" in driver.page_source

    def test_clone(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        # Find the expense card and click its Clone button
        card = driver.execute_script(
            "return Array.from(document.querySelectorAll('.exp-card')).find("
            "  c => c.querySelector('.exp-title')?.textContent?.trim() === 'E2E Expense Edited'"
            ");"
        )
        assert card is not None, "Could not find 'E2E Expense Edited' card in expense list"
        card.find_element(By.XPATH, ".//button[text()='Clone']").click()
        time.sleep(2)
        ctx["clone_uid"] = re.search(r'/expenses/(\d+)/edit/', driver.current_url).group(1)
        assert "CLONE - E2E Expense Edited" in driver.find_element(By.ID, "id_title").get_attribute("value")
        submit(w)
        time.sleep(2)

    def test_delete_clone(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        card = driver.execute_script(
            "return Array.from(document.querySelectorAll('.exp-card')).find("
            "  c => c.querySelector('.exp-title')?.textContent?.trim() === 'CLONE - E2E Expense Edited'"
            ");"
        )
        assert card is not None, "Could not find clone card in expense list"
        card.find_element(By.XPATH, ".//button[text()='Delete']").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert "CLONE - E2E Expense Edited" not in driver.page_source

    def test_all_fields_round_trip(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        fill(w, By.ID, "id_title", "E2E AllFields")
        fill(w, By.ID, "id_value", "77.77")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_payee", "Test Payee")
        fill(w, By.ID, "id_note", "Test note")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_auto_settle_on_due_date').checked = true;"
        )
        submit(w)
        time.sleep(2)
        # Presentation already covered by other tests; verify via API
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "E2E AllFields"})
        assert resp.status_code == 200
        data = resp.json()["expenses"][0]
        assert data["payee"] == "Test Payee"
        assert data["note"] == "Test note"
        assert data["auto_settle_on_due_date"] is True
        api_delete(f"/api/v1/expenses/{data['id']}/", ctx)

    def test_type_income(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        fill(w, By.ID, "id_title", "E2E Income")
        fill(w, By.ID, "id_value", "500.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("income")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        submit(w)
        time.sleep(2)
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "E2E Income"})
        assert resp.status_code == 200
        data = resp.json()["expenses"][0]
        assert data["type"] == "income"
        ctx["income_id"] = data["id"]

    def test_type_savings(self, driver, w, ctx):
        today = server_today()
        # savings_dep
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        fill(w, By.ID, "id_title", "E2E SavingsDep")
        fill(w, By.ID, "id_value", "200.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("savings_dep")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        submit(w)
        time.sleep(2)
        dep = api_get("/api/v1/expenses/", ctx, params={"q": "E2E SavingsDep"})
        assert dep.json()["expenses"][0]["type"] == "savings_dep"
        ctx["dep_id"] = dep.json()["expenses"][0]["id"]
        # savings_wit
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        fill(w, By.ID, "id_title", "E2E SavingsWit")
        fill(w, By.ID, "id_value", "50.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("savings_wit")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        submit(w)
        time.sleep(2)
        wit = api_get("/api/v1/expenses/", ctx, params={"q": "E2E SavingsWit"})
        assert wit.json()["expenses"][0]["type"] == "savings_wit"
        ctx["wit_id"] = wit.json()["expenses"][0]["id"]

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
