"""Expense CRUD via browser, plus all-fields browser round-trip and CSV export."""
import re
import time

import requests
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import (
    _url, fill, submit, server_today,
    session_cookies, api_get, api_post, api_delete,
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


class TestExpenseSorting:

    @pytest.fixture(scope="class")
    def sctx(self, driver, w):
        c = setup_user(driver, w)
        today = server_today()
        year, month = today[:4], str(int(today[5:7]))
        ids = []
        for title, value in [("ZZZ Sort", "10.00"), ("AAA Sort", "50.00"), ("MMM Sort", "30.00")]:
            r = api_post("/api/v1/expenses/", c, json={
                "title": title, "value": value, "type": "expense",
                "date_due": today, "settled": True,
            })
            assert r.status_code == 201
            ids.append(r.json()["id"])
        c["sort_ids"] = ids
        c["sort_year"] = year
        c["sort_month"] = month
        yield c
        for uid in ids:
            api_delete(f"/api/v1/expenses/{uid}/", c)
        cleanup_user(c["email"])

    def _card_titles(self, driver):
        return driver.execute_script(
            "return Array.from(document.querySelectorAll('.exp-title'))"
            ".map(e => e.textContent.trim());"
        )

    def test_sort_title_asc(self, driver, w, sctx):
        driver.get(_url(
            f"/budget/expenses/?year={sctx['sort_year']}&month={sctx['sort_month']}"
        ))
        time.sleep(2)
        # Change to title asc via the sort dropdowns
        sort_by_sel = Select(driver.find_element(By.ID, "exp-sort-by"))
        sort_dir_sel = Select(driver.find_element(By.ID, "exp-sort-dir"))
        sort_by_sel.select_by_value("title")
        time.sleep(0.1)
        sort_dir_sel.select_by_value("asc")
        time.sleep(2)
        titles = self._card_titles(driver)
        sort_titles = [t for t in titles if t.endswith(" Sort")]
        assert sort_titles == ["AAA Sort", "MMM Sort", "ZZZ Sort"], sort_titles

    def test_sort_value_desc(self, driver, w, sctx):
        sort_by_sel = Select(driver.find_element(By.ID, "exp-sort-by"))
        sort_dir_sel = Select(driver.find_element(By.ID, "exp-sort-dir"))
        sort_by_sel.select_by_value("value")
        time.sleep(0.1)
        sort_dir_sel.select_by_value("desc")
        time.sleep(2)
        values = driver.execute_script(
            "return Array.from(document.querySelectorAll('.exp-amount'))"
            ".map(e => parseFloat(e.textContent.trim()));"
        )
        sort_values = [v for v in values if v in (10.0, 30.0, 50.0)]
        assert sort_values == [50.0, 30.0, 10.0], sort_values

    def test_sort_date_desc_default(self, driver, w, sctx):
        # Reload the page to confirm default is date desc (no explicit change needed)
        driver.get(_url(
            f"/budget/expenses/?year={sctx['sort_year']}&month={sctx['sort_month']}"
        ))
        time.sleep(2)
        sort_by_sel = Select(driver.find_element(By.ID, "exp-sort-by"))
        sort_dir_sel = Select(driver.find_element(By.ID, "exp-sort-dir"))
        assert sort_by_sel.first_selected_option.get_attribute("value") == "date"
        assert sort_dir_sel.first_selected_option.get_attribute("value") == "desc"


class TestDoubleSubmitGuard:
    """Verify that posting a consumed nonce (back + resubmit) does not create a duplicate.

    Uses a plain requests.Session so the test is independent of browser login state.
    """

    def test_back_resubmit_creates_only_one_expense(self, ctx):
        import re as _re

        s = requests.Session()
        today = server_today()
        title = "E2E NoDuplicate"

        # --- authenticate ---
        # GET /login/ to receive the CSRF cookie, then POST credentials.
        r = s.get(_url("/login/"))
        assert r.status_code == 200, f"GET /login/ returned {r.status_code}"
        csrf = s.cookies.get("csrftoken", "")
        r = s.post(_url("/login/"), data={
            "csrfmiddlewaretoken": csrf,
            "email": ctx["email"],
            "password": ctx["password"],
        }, allow_redirects=True)
        assert "/budget/" in r.url, f"Login did not redirect to /budget/; landed at {r.url}"

        # --- load the form and capture the one-time nonce ---
        r = s.get(_url("/budget/expenses/new/"))
        assert r.status_code == 200, f"GET /budget/expenses/new/ returned {r.status_code}"
        m = _re.search(r'name="form_nonce"\s+value="([^"]+)"', r.text)
        assert m, "form_nonce hidden input not found in expense form HTML"
        stale_nonce = m.group(1)
        csrf = s.cookies.get("csrftoken", csrf)

        post_data = {
            "csrfmiddlewaretoken": csrf,
            "form_nonce": stale_nonce,
            "title": title,
            "value": "9.99",
            "type": "expense",
            "date_due": today,
            "settled": "on",
        }

        # --- first POST: creates the expense and consumes the nonce ---
        r = s.post(_url("/budget/expenses/new/"), data=post_data, allow_redirects=False)
        assert r.status_code in (301, 302), f"First POST returned {r.status_code}"

        # --- second POST: replay the consumed nonce (back + resubmit) ---
        post_data["title"] = title + " DUPE"
        r = s.post(_url("/budget/expenses/new/"), data=post_data, allow_redirects=False)
        assert r.status_code in (301, 302), f"Second POST returned {r.status_code}"

        # --- assert only one expense was created ---
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "E2E NoDuplicate"})
        assert resp.status_code == 200
        matches = resp.json()["expenses"]
        dupes = [e for e in matches if "DUPE" in e["title"]]
        assert dupes == [], f"Duplicate expense was created: {dupes}"
        originals = [e for e in matches if e["title"] == title]
        assert len(originals) == 1, f"Expected 1 original, found {len(originals)}"
        api_delete(f"/api/v1/expenses/{originals[0]['id']}/", ctx)
