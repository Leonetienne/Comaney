"""
Selenium end-to-end test suite for Comaney.

Requirements:
    pip install selenium pytest pyotp requests

The app must be running at http://localhost:8080 and mailpit at http://localhost:8030.
Tests are ordered and share a single browser session via class variables.
"""
import re
import tempfile
import time
import uuid
from datetime import date

import pyotp
import pytest
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

BASE_URL     = "http://localhost:8080"
MAILPIT_API  = "http://localhost:8030/api/v1"
PASSWORD     = "S3l3n!umTest"
TIMEOUT      = 60  # seconds — generous to accommodate PoW captcha


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


@pytest.fixture(scope="module")
def ctx():
    """Shared mutable context dict passed to every test."""
    return {}


@pytest.fixture(scope="module")
def driver():
    tmpdir = tempfile.mkdtemp()
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument(f"--user-data-dir={tmpdir}")
    d = webdriver.Chrome(options=opts)
    d.implicitly_wait(0)  # we use explicit waits everywhere
    yield d
    d.quit()


@pytest.fixture(scope="module")
def w(driver):
    return WebDriverWait(driver, TIMEOUT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_url(w, fragment):
    w.until(EC.url_contains(fragment))


def wait_text(driver, w, text):
    w.until(lambda d: text in d.page_source)


def fill(w, by, locator, value):
    el = w.until(EC.element_to_be_clickable((by, locator)))
    el.clear()
    el.send_keys(value)


def click(w, by, locator):
    el = w.until(EC.element_to_be_clickable((by, locator)))
    el.click()


def fetch_email(to_email: str, subject_fragment: str, timeout: int = 60) -> str:
    """Poll mailpit until a matching email arrives; return its plain-text body."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
            for msg in msgs:
                recipients = [t.get("Address", "") for t in msg.get("To", [])]
                if to_email in recipients and subject_fragment.lower() in msg.get("Subject", "").lower():
                    body = requests.get(f"{MAILPIT_API}/message/{msg['ID']}", timeout=5).json()
                    return body.get("Text", "") or ""
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"Email '{subject_fragment}' for {to_email} never arrived")


def extract_link(text: str) -> str:
    """Pull the first HTTP URL from email text and rewrite the host to BASE_URL."""
    for raw in re.findall(r'https?://\S+', text):
        url = raw.rstrip('.,)')
        return re.sub(r'https?://[^/]+', BASE_URL, url)
    raise ValueError("No URL found in email body")


# ---------------------------------------------------------------------------
# Tests — run in definition order (pytest default within a module)
# ---------------------------------------------------------------------------

class TestComaney:

    # ── Registration ────────────────────────────────────────────────────────

    def test_01_register(self, driver, w, ctx):
        ctx["email"] = f"selenium.{uuid.uuid4().hex[:8]}@example.com"
        # Clear mailpit so old messages don't interfere
        try:
            requests.delete(f"{MAILPIT_API}/messages", timeout=5)
        except Exception:
            pass

        driver.get(_url("/register/"))
        fill(w, By.ID, "id_first_name", "Selenium")
        fill(w, By.ID, "id_last_name", "Tester")
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", PASSWORD)
        fill(w, By.ID, "id_password_confirm", PASSWORD)

        # Wait for PoW worker to solve the captcha and enable the submit button
        w.until(lambda d: not d.find_element(By.ID, "submit-btn").get_attribute("disabled"))

        driver.find_element(By.ID, "submit-btn").click()
        wait_url(w, "/register/success/")

    def test_02_confirm_email(self, driver, w, ctx):
        body = fetch_email(ctx["email"], "confirm")
        driver.get(extract_link(body))
        wait_text(driver, w, "confirmed")

    # ── Login ────────────────────────────────────────────────────────────────

    def test_03_login(self, driver, w, ctx):
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        wait_url(w, "/budget/")

    # ── Dashboard ────────────────────────────────────────────────────────────

    def test_04_dashboard(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        wait_text(driver, w, "Left to spend")

    # ── Categories & Tags ────────────────────────────────────────────────────

    def test_05_create_category(self, driver, w, ctx):
        driver.get(_url("/budget/categories-tags/"))
        inp = w.until(EC.element_to_be_clickable((By.ID, "category-input")))
        inp.send_keys("Test Category" + Keys.RETURN)
        w.until(lambda d: "Test Category" in d.find_element(By.ID, "category-list").text)

    def test_06_rename_category(self, driver, w, ctx):
        print(f"\n[DEBUG test_06] start URL: {driver.current_url}")
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#category-list .ct-name")))
        ctx["category_uid"] = driver.execute_script(
            "return document.querySelector('#category-list .ct-name').dataset.uid;")
        driver.execute_script(
            "var el=document.querySelector('#category-list .ct-name');"
            "el.scrollIntoView({block:'center'}); el.click();")
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#category-list .ct-name-input")))
        driver.execute_script(
            "var inp=document.querySelector('#category-list .ct-name-input');"
            "inp.value='Renamed Category';"
            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        # Wait for the fetch to update the span then reload to confirm persistence
        time.sleep(0.5)
        driver.get(_url("/budget/categories-tags/"))
        print(f"\n[DEBUG test_06] after reload URL: {driver.current_url}")
        wait_text(driver, w, "Renamed Category")

    def test_07_create_tag(self, driver, w, ctx):
        inp = w.until(EC.element_to_be_clickable((By.ID, "tag-input")))
        inp.send_keys("Test Tag" + Keys.RETURN)
        w.until(lambda d: "Test Tag" in d.find_element(By.ID, "tag-list").text)

    def test_08_rename_tag(self, driver, w, ctx):
        print(f"\n[DEBUG test_08] start URL: {driver.current_url}")
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tag-list .ct-name")))
        ctx["tag_uid"] = driver.execute_script(
            "return document.querySelector('#tag-list .ct-name').dataset.uid;")
        driver.execute_script(
            "var el=document.querySelector('#tag-list .ct-name');"
            "el.scrollIntoView({block:'center'}); el.click();")
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tag-list .ct-name-input")))
        driver.execute_script(
            "var inp=document.querySelector('#tag-list .ct-name-input');"
            "inp.value='Renamed Tag';"
            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        time.sleep(0.5)
        driver.get(_url("/budget/categories-tags/"))
        print(f"\n[DEBUG test_08] after reload URL: {driver.current_url}")
        wait_text(driver, w, "Renamed Tag")

    # ── Expenses ─────────────────────────────────────────────────────────────

    def test_09_create_expense(self, driver, w, ctx):
        print(f"\n[DEBUG test_09] start URL: {driver.current_url}")
        today = date.today().isoformat()
        driver.get(_url("/budget/expenses/new/"))
        print(f"\n[DEBUG test_09] after navigate URL: {driver.current_url}")
        fill(w, By.ID, "id_title", "Selenium Expense")
        fill(w, By.ID, "id_value", "42.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        # Set date and settled via JS — date inputs are finicky cross-platform,
        # and settled=True makes date_due non-required as a fallback
        driver.execute_script(f"""
            document.getElementById('id_date_due').value = '{today}';
            document.getElementById('id_settled').checked = true;
        """)
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")
        # Wait for redirect to the list (URL ends at /budget/expenses/ with no further path)
        w.until(lambda d: d.current_url.rstrip("/").endswith("/budget/expenses"))
        wait_text(driver, w, "Selenium Expense")

    def test_10_edit_expense(self, driver, w, ctx):
        # Find the edit link for our expense
        link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//span[contains(text(),'Selenium Expense')]"
                       "/ancestor::div[contains(@class,'exp-card')]"
                       "//a[contains(@href,'/edit/')]")))
        href = link.get_attribute("href")
        ctx["expense_uid"] = re.search(r'/expenses/(\d+)/edit/', href).group(1)
        link.click()
        fill(w, By.ID, "id_title", "Selenium Expense Edited")
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")
        wait_url(w, "/budget/expenses/")
        wait_text(driver, w, "Selenium Expense Edited")

    def test_11_clone_expense(self, driver, w, ctx):
        clone_btn = w.until(EC.element_to_be_clickable(
            (By.XPATH, f"//form[contains(@action,'/expenses/{ctx['expense_uid']}/clone/')]"
                       "//button")))
        clone_btn.click()
        # Lands on edit form for the clone
        wait_url(w, "/edit/")
        w.until(lambda d: "CLONE - Selenium Expense Edited" in d.find_element(By.ID, "id_title").get_attribute("value"))
        # Grab clone UID from URL for later deletion
        ctx["clone_expense_uid"] = re.search(r'/expenses/(\d+)/edit/', driver.current_url).group(1)
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")
        wait_url(w, "/budget/expenses/")

    def test_12_delete_cloned_expense(self, driver, w, ctx):
        delete_form = w.until(EC.presence_of_element_located(
            (By.XPATH, f"//form[contains(@action,'/expenses/{ctx['clone_expense_uid']}/delete/')]")))
        driver.execute_script("arguments[0].querySelector('button').click()", delete_form)
        # confirmDialog appears — click OK to confirm deletion
        ok_btn = w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok")))
        ok_btn.click()
        w.until(lambda d: d.current_url.rstrip("/").endswith("/budget/expenses"))
        # Confirm the original still exists but clone is gone
        wait_text(driver, w, "Selenium Expense Edited")
        w.until(lambda d: f"CLONE - Selenium Expense Edited" not in d.page_source
                or d.page_source.count("CLONE - Selenium Expense Edited") == 0)

    # ── Scheduled expenses ───────────────────────────────────────────────────

    def test_13_create_scheduled(self, driver, w, ctx):
        today = date.today().isoformat()
        driver.get(_url("/budget/scheduled/new/"))
        fill(w, By.ID, "id_title", "Selenium Scheduled")
        fill(w, By.ID, "id_value", "99.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script(
            f"document.getElementById('id_repeat_base_date').value = '{today}';"
        )
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "Selenium Scheduled")

    def test_14_edit_scheduled(self, driver, w, ctx):
        link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//span[contains(text(),'Selenium Scheduled')]"
                       "/ancestor::div[contains(@class,'exp-card')]"
                       "//a[contains(@href,'/edit/')]")))
        href = link.get_attribute("href")
        ctx["scheduled_uid"] = re.search(r'/scheduled/(\d+)/edit/', href).group(1)
        link.click()
        fill(w, By.ID, "id_title", "Selenium Scheduled Edited")
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "Selenium Scheduled Edited")

    def test_15_clone_scheduled(self, driver, w, ctx):
        clone_btn = w.until(EC.element_to_be_clickable(
            (By.XPATH, f"//form[contains(@action,'/scheduled/{ctx['scheduled_uid']}/clone/')]"
                       "//button")))
        clone_btn.click()
        wait_url(w, "/edit/")
        w.until(lambda d: "CLONE - Selenium Scheduled Edited" in d.find_element(By.ID, "id_title").get_attribute("value"))
        ctx["clone_scheduled_uid"] = re.search(r'/scheduled/(\d+)/edit/', driver.current_url).group(1)
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")
        wait_url(w, "/budget/scheduled/")

    def test_16_delete_cloned_scheduled(self, driver, w, ctx):
        delete_form = w.until(EC.presence_of_element_located(
            (By.XPATH, f"//form[contains(@action,'/scheduled/{ctx['clone_scheduled_uid']}/delete/')]")))
        driver.execute_script("arguments[0].querySelector('button').click()", delete_form)
        ok_btn = w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok")))
        ok_btn.click()
        w.until(lambda d: d.current_url.rstrip("/").endswith("/budget/scheduled"))

    # ── Profile ──────────────────────────────────────────────────────────────

    def test_17_update_profile(self, driver, w, ctx):
        time.sleep(1)
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Personal info")
        fill(w, By.ID, "id_currency", "$")
        driver.execute_script(
            "document.querySelector(\"input[name='action'][value='profile']\").closest('form').submit()"
        )
        wait_url(w, "/profile/")
        wait_text(driver, w, "Saved.")

    # ── API key ──────────────────────────────────────────────────────────────

    def test_18_generate_api_key(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Personal info")
        click(w, By.XPATH, "//form[contains(@action,'api-key/generate')]//button")
        wait_url(w, "/profile/")
        key_el = w.until(EC.presence_of_element_located((By.ID, "api-key-display")))
        ctx["api_key"] = key_el.get_attribute("value")
        assert len(ctx["api_key"]) > 10

    def test_19_api_key_works(self, driver, w, ctx):
        time.sleep(1)
        resp = requests.get(
            f"{BASE_URL}/api/v1/account/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == ctx["email"]

    # ── API: account ─────────────────────────────────────────────────────────

    def test_20_api_account_patch(self, driver, w, ctx):
        resp = requests.patch(
            f"{BASE_URL}/api/v1/account/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            json={"currency": "€", "month_start_day": 1},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["currency"] == "€"
        assert data["month_start_day"] == 1

    # ── API: dashboard ────────────────────────────────────────────────────────

    def test_21_api_dashboard(self, driver, w, ctx):
        resp = requests.get(
            f"{BASE_URL}/api/v1/dashboard/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "income" in data
        assert "balance" in data
        assert "month_range" in data

    # ── API: categories ───────────────────────────────────────────────────────

    def test_22_api_category_create(self, driver, w, ctx):
        resp = requests.post(
            f"{BASE_URL}/api/v1/categories/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            json={"title": "API Category"},
            timeout=10,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "API Category"
        ctx["api_cat_id"] = data["id"]

    def test_23_api_category_list(self, driver, w, ctx):
        resp = requests.get(
            f"{BASE_URL}/api/v1/categories/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()["categories"]]
        assert ctx["api_cat_id"] in ids

    def test_24_api_category_get(self, driver, w, ctx):
        resp = requests.get(
            f"{BASE_URL}/api/v1/categories/{ctx['api_cat_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Category"

    def test_25_api_category_patch(self, driver, w, ctx):
        resp = requests.patch(
            f"{BASE_URL}/api/v1/categories/{ctx['api_cat_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            json={"title": "API Category Renamed"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Category Renamed"

    def test_26_api_category_delete(self, driver, w, ctx):
        resp = requests.delete(
            f"{BASE_URL}/api/v1/categories/{ctx['api_cat_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 204
        # Verify it's gone
        resp2 = requests.get(
            f"{BASE_URL}/api/v1/categories/{ctx['api_cat_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp2.status_code == 404

    # ── API: tags ─────────────────────────────────────────────────────────────

    def test_27_api_tag_create(self, driver, w, ctx):
        resp = requests.post(
            f"{BASE_URL}/api/v1/tags/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            json={"title": "API Tag"},
            timeout=10,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "API Tag"
        ctx["api_tag_id"] = data["id"]

    def test_28_api_tag_list(self, driver, w, ctx):
        resp = requests.get(
            f"{BASE_URL}/api/v1/tags/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()["tags"]]
        assert ctx["api_tag_id"] in ids

    def test_29_api_tag_get(self, driver, w, ctx):
        resp = requests.get(
            f"{BASE_URL}/api/v1/tags/{ctx['api_tag_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Tag"

    def test_30_api_tag_patch(self, driver, w, ctx):
        resp = requests.patch(
            f"{BASE_URL}/api/v1/tags/{ctx['api_tag_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            json={"title": "API Tag Renamed"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Tag Renamed"

    def test_31_api_tag_delete(self, driver, w, ctx):
        resp = requests.delete(
            f"{BASE_URL}/api/v1/tags/{ctx['api_tag_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 204
        resp2 = requests.get(
            f"{BASE_URL}/api/v1/tags/{ctx['api_tag_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp2.status_code == 404

    # ── API: expenses ─────────────────────────────────────────────────────────

    def test_32_api_expense_create(self, driver, w, ctx):
        resp = requests.post(
            f"{BASE_URL}/api/v1/expenses/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            json={"title": "API Expense", "type": "expense", "value": "12.34",
                  "date_due": date.today().isoformat(), "settled": True},
            timeout=10,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "API Expense"
        assert data["value"] == "12.34"
        ctx["api_expense_id"] = data["id"]

    def test_33_api_expense_list(self, driver, w, ctx):
        resp = requests.get(
            f"{BASE_URL}/api/v1/expenses/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        ids = [e["id"] for e in resp.json()["expenses"]]
        assert ctx["api_expense_id"] in ids

    def test_34_api_expense_get(self, driver, w, ctx):
        resp = requests.get(
            f"{BASE_URL}/api/v1/expenses/{ctx['api_expense_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Expense"

    def test_35_api_expense_patch(self, driver, w, ctx):
        resp = requests.patch(
            f"{BASE_URL}/api/v1/expenses/{ctx['api_expense_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            json={"title": "API Expense Edited", "value": "99.99"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "API Expense Edited"
        assert data["value"] == "99.99"

    def test_36_api_expense_delete(self, driver, w, ctx):
        resp = requests.delete(
            f"{BASE_URL}/api/v1/expenses/{ctx['api_expense_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 204
        resp2 = requests.get(
            f"{BASE_URL}/api/v1/expenses/{ctx['api_expense_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp2.status_code == 404

    # ── API: scheduled expenses ───────────────────────────────────────────────

    def test_37_api_scheduled_create(self, driver, w, ctx):
        resp = requests.post(
            f"{BASE_URL}/api/v1/scheduled/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            json={"title": "API Scheduled", "type": "expense", "value": "50.00",
                  "repeat_every_factor": 1, "repeat_every_unit": "months",
                  "repeat_base_date": date.today().isoformat()},
            timeout=10,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "API Scheduled"
        assert data["repeat_every_unit"] == "months"
        ctx["api_scheduled_id"] = data["id"]

    def test_38_api_scheduled_list(self, driver, w, ctx):
        resp = requests.get(
            f"{BASE_URL}/api/v1/scheduled/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()["scheduled"]]
        assert ctx["api_scheduled_id"] in ids

    def test_39_api_scheduled_get(self, driver, w, ctx):
        resp = requests.get(
            f"{BASE_URL}/api/v1/scheduled/{ctx['api_scheduled_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Scheduled"

    def test_40_api_scheduled_patch(self, driver, w, ctx):
        resp = requests.patch(
            f"{BASE_URL}/api/v1/scheduled/{ctx['api_scheduled_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            json={"title": "API Scheduled Edited", "repeat_every_unit": "weeks"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "API Scheduled Edited"
        assert data["repeat_every_unit"] == "weeks"

    def test_41_api_scheduled_delete(self, driver, w, ctx):
        resp = requests.delete(
            f"{BASE_URL}/api/v1/scheduled/{ctx['api_scheduled_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 204
        resp2 = requests.get(
            f"{BASE_URL}/api/v1/scheduled/{ctx['api_scheduled_id']}/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp2.status_code == 404

    # ── API key revoke ────────────────────────────────────────────────────────

    def test_42_revoke_api_key(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Personal info")
        click(w, By.XPATH, "//form[contains(@action,'api-key/revoke')]//button")
        wait_url(w, "/profile/")
        time.sleep(1)
        resp = requests.get(
            f"{BASE_URL}/api/v1/account/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 401

    # ── Two-factor authentication ────────────────────────────────────────────

    def test_43_setup_2fa(self, driver, w, ctx):
        driver.get(_url("/totp/setup/"))
        # Expand the manual key section to read the TOTP secret
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        ctx["totp_secret"] = secret_el.text.strip()

        code = pyotp.TOTP(ctx["totp_secret"]).now()
        fill(w, By.ID, "id_code", code)
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")

        # Recovery code screen
        recovery_el = w.until(EC.presence_of_element_located((By.ID, "recovery-code")))
        ctx["recovery_code"] = recovery_el.text.strip()
        click(w, By.CSS_SELECTOR, "a.btn")  # Done button

    def test_44_login_with_totp(self, driver, w, ctx):
        click(w, By.CSS_SELECTOR, "button[type=submit]#logout-button")
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")

        # Should be on TOTP verify page
        wait_url(w, "/totp/verify/")
        code = pyotp.TOTP(ctx["totp_secret"]).now()
        fill(w, By.ID, "id_code", code)
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")
        wait_url(w, "/budget/")

    def test_45_disable_2fa(self, driver, w, ctx):
        driver.get(_url("/totp/disable/"))
        code = pyotp.TOTP(ctx["totp_secret"]).now()
        fill(w, By.ID, "id_code", code)
        click(w, By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)")
        wait_url(w, "/profile/")
        # 2FA should now show as disabled
        wait_text(driver, w, "Not enabled")

    # ── Categories & tags cleanup ─────────────────────────────────────────────

    def _delete_ct_item(self, driver, w, item_id):
        """Click the × button for a category/tag item and confirm via the modal OK button."""
        btn = w.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f"#{item_id} .ct-delete")))
        btn.click()
        # Click OK on the custom confirm dialog
        ok_btn = w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok")))
        ok_btn.click()
        w.until(EC.invisibility_of_element_located((By.ID, item_id)))

    def test_46_delete_category(self, driver, w, ctx):
        driver.get(_url("/budget/categories-tags/"))
        self._delete_ct_item(driver, w, f"category-{ctx['category_uid']}")

    def test_47_delete_tag(self, driver, w, ctx):
        self._delete_ct_item(driver, w, f"tag-{ctx['tag_uid']}")

    # ── Account deletion ─────────────────────────────────────────────────────

    def test_48_delete_account(self, driver, w, ctx):
        driver.get(_url("/account/delete/"))
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        # Should redirect to home / login after deletion
        w.until(lambda d: "/budget/" not in d.current_url)
