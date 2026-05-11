"""
Shared helpers for tests_new.
All test files import from here; conftest.py provides the driver/w fixtures.

User lifecycle: each test file creates its own user via setup_user(), and
cleans up via cleanup_user().  cleanup_user() uses docker exec so it is
safe regardless of browser state (TOTP enabled, logged out, etc.).
"""
import re
import subprocess
import time
import uuid

import pytest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

BASE_URL    = "http://localhost:8080"
MAILPIT_API = "http://localhost:8030/api/v1"
PASSWORD    = "S3l3n!umTest"
TIMEOUT     = 60
CLICK_PACE  = 0.15
DOCKER_WEB  = "comaney-web-1"
SUBMIT_BTN  = "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)"


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


# ── Browser helpers ───────────────────────────────────────────────────────────

def fill(w, by, locator, value):
    el = w.until(EC.element_to_be_clickable((by, locator)))
    el.clear()
    el.send_keys(value)
    time.sleep(CLICK_PACE)


def click(w, by, locator):
    w.until(EC.element_to_be_clickable((by, locator))).click()
    time.sleep(CLICK_PACE)


def submit(w):
    click(w, By.CSS_SELECTOR, SUBMIT_BTN)


def wait_url(w, fragment):
    w.until(EC.url_contains(fragment))


def wait_text(driver, w, text):
    w.until(lambda d: text in d.page_source)


def wait_no_text(driver, w, text):
    w.until(lambda d: text not in d.page_source)


def session_cookies(driver) -> dict:
    return {c["name"]: c["value"] for c in driver.get_cookies()}


# ── Email helpers ─────────────────────────────────────────────────────────────

def mailpit_seen_ids() -> set:
    try:
        msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
        return {m["ID"] for m in msgs}
    except Exception:
        return set()


def fetch_email(to_email: str, subject_fragment: str, timeout: int = 60,
                ignore_ids=None) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
            for msg in msgs:
                if ignore_ids and msg["ID"] in ignore_ids:
                    continue
                recipients = [t.get("Address", "") for t in msg.get("To", [])]
                subject_match = subject_fragment.lower() in msg.get("Subject", "").lower()
                if to_email in recipients and subject_match:
                    body = requests.get(f"{MAILPIT_API}/message/{msg['ID']}", timeout=5).json()
                    return body.get("Text", "") or ""
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"Email '{subject_fragment}' for {to_email} never arrived")


def extract_link(text: str) -> str:
    for raw in re.findall(r'https?://\S+', text):
        url = raw.rstrip('.,)')
        return re.sub(r'https?://[^/]+', BASE_URL, url)
    raise ValueError("No URL found in email body")


# ── API helpers ───────────────────────────────────────────────────────────────

def api(method: str, path: str, ctx: dict, **kwargs):
    return requests.request(
        method, f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {ctx['api_key']}"},
        timeout=10, **kwargs,
    )


def api_get(path, ctx, params=None):   return api("GET",    path, ctx, params=params)
def api_post(path, ctx, json):         return api("POST",   path, ctx, json=json)
def api_patch(path, ctx, json):        return api("PATCH",  path, ctx, json=json)
def api_delete(path, ctx):             return api("DELETE", path, ctx)


# ── Docker / management command helpers ───────────────────────────────────────

def run_cmd(*args, timeout: int = 30) -> str:
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", *args],
        capture_output=True, text=True, timeout=timeout,
    )
    assert result.returncode == 0, f"Management command failed:\n{result.stderr}"
    return result.stdout


def server_today() -> str:
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "-c",
         "from datetime import date; print(date.today().isoformat())"],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout.strip()


# ── User lifecycle ────────────────────────────────────────────────────────────

def register_user(driver, w) -> dict:
    """Register a fresh user via the UI. Returns ctx dict with email and password."""
    driver.delete_all_cookies()
    driver.execute_script("sessionStorage.clear(); localStorage.clear();")
    email = f"sel.{uuid.uuid4().hex[:8]}@example.com"
    try:
        requests.delete(f"{MAILPIT_API}/messages", timeout=5)
    except Exception:
        pass
    driver.get(_url("/register/"))
    fill(w, By.ID, "id_first_name", "Selenium")
    fill(w, By.ID, "id_last_name", "Tester")
    fill(w, By.ID, "id_email", email)
    fill(w, By.ID, "id_password", PASSWORD)
    fill(w, By.ID, "id_password_confirm", PASSWORD)
    w.until(lambda d: not d.find_element(By.ID, "submit-btn").get_attribute("disabled"))
    driver.find_element(By.ID, "submit-btn").click()
    wait_url(w, "/register/success/")
    return {"email": email, "password": PASSWORD}


def confirm_email(driver, w, ctx):
    """Confirm email address by following the link sent to mailpit."""
    body = fetch_email(ctx["email"], "confirm")
    driver.get(extract_link(body))
    wait_text(driver, w, "confirmed")


def browser_login(driver, w, email: str, password: str):
    """Log in via the browser login form. Navigates to /login/ first."""
    driver.get(_url("/login/"))
    fill(w, By.ID, "id_email", email)
    fill(w, By.ID, "id_password", password)
    click(w, By.CSS_SELECTOR, "button[type=submit]")
    wait_url(w, "/budget/")


def get_api_key(driver, w) -> str:
    """Generate and return a fresh API key from the profile page."""
    driver.get(_url("/profile/"))
    wait_text(driver, w, "Personal info")
    click(w, By.XPATH, "//form[contains(@action,'api-key/generate')]//button")
    wait_url(w, "/profile/")
    key_el = w.until(EC.presence_of_element_located((By.ID, "api-key-display")))
    return key_el.get_attribute("value")


def setup_user(driver, w) -> dict:
    """Full user setup: register, confirm email, log in, generate API key."""
    ctx = register_user(driver, w)
    confirm_email(driver, w, ctx)
    browser_login(driver, w, ctx["email"], ctx["password"])
    ctx["api_key"] = get_api_key(driver, w)
    return ctx


def cleanup_user(email: str):
    """Delete a test user directly via docker exec (safe regardless of browser state)."""
    subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c",
         f"from feusers.models import FeUser; FeUser.objects.filter(email='{email}').delete()"],
        capture_output=True, text=True, timeout=10,
    )


def user_fixture(driver, w):
    """
    Module-scoped user fixture factory. Use as:
        @pytest.fixture(scope="module")
        def ctx(driver, w):
            yield from user_fixture(driver, w)
    """
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])
