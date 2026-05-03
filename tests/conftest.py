"""
Shared fixtures and helpers for the Comaney E2E test suite.

Requirements:
    pip install selenium pytest pyotp requests

The app must be running at http://localhost:8080 and mailpit at http://localhost:8030.
All tests share a single browser session and ctx dict (session-scoped fixtures).
Test files are named with numeric prefixes so pytest runs them in the right order.
"""
import re
import subprocess
import tempfile
import time

import pytest
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL    = "http://localhost:8080"
MAILPIT_API = "http://localhost:8030/api/v1"
PASSWORD    = "S3l3n!umTest"
TIMEOUT     = 60  # seconds — generous to accommodate PoW captcha
DOCKER_WEB  = "comaney-web-1"


def pytest_configure(config):
    """Abort immediately if the server isn't wired up to Mailpit."""
    try:
        result = subprocess.run(
            ["docker", "exec", DOCKER_WEB, "python", "-c",
             "import os\n"
             "print(os.environ.get('DISABLE_EMAILING','').upper())\n"
             "print(os.environ.get('EMAIL_HOST',''))"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return  # container not ready yet — let tests fail naturally
        lines = result.stdout.splitlines()
        if len(lines) < 2:
            return  # unexpected output — don't block
        disable_emailing = lines[0].strip()
        email_host       = lines[1].strip()
    except Exception:
        return  # container unreachable — let tests fail naturally

    if disable_emailing in ("1", "TRUE", "YES"):
        pytest.exit(
            "\nABORT: DISABLE_EMAILING is set on the server.\n"
            "Please configure Mailpit as the mail server (EMAIL_HOST=mailpit, EMAIL_PORT=1025)\n"
            "and remove DISABLE_EMAILING before running the test suite.\n",
            returncode=1,
        )

    if email_host.lower() != "mailpit":
        pytest.exit(
            f"\nABORT: EMAIL_HOST is '{email_host}' — expected 'mailpit'.\n"
            "Please set up Mailpit as the mail server (EMAIL_HOST=mailpit, EMAIL_PORT=1025)\n"
            "before running the test suite.\n",
            returncode=1,
        )

# Small post-click pause — acts as a natural pace-setter so the server and browser
# can breathe between interactions, avoiding most ad-hoc time.sleep() calls.
CLICK_PACE  = 0.15


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


@pytest.fixture(scope="session")
def ctx():
    """Shared mutable context dict passed to every test across all files."""
    return {}


@pytest.fixture(scope="session")
def driver():
    tmpdir = tempfile.mkdtemp()
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument(f"--user-data-dir={tmpdir}")
    d = webdriver.Chrome(options=opts)
    d.implicitly_wait(0)
    yield d
    d.quit()


@pytest.fixture(scope="session")
def w(driver):
    return WebDriverWait(driver, TIMEOUT)


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def wait_url(w, fragment):
    w.until(EC.url_contains(fragment))


def wait_text(driver, w, text):
    w.until(lambda d: text in d.page_source)


def wait_no_text(driver, w, text):
    w.until(lambda d: text not in d.page_source)


def fill(w, by, locator, value):
    el = w.until(EC.element_to_be_clickable((by, locator)))
    el.clear()
    el.send_keys(value)
    time.sleep(CLICK_PACE)


def click(w, by, locator):
    el = w.until(EC.element_to_be_clickable((by, locator)))
    el.click()
    time.sleep(CLICK_PACE)


SUBMIT = "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)"


def submit(w):
    click(w, By.CSS_SELECTOR, SUBMIT)


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def mailpit_seen_ids() -> set:
    """Return the set of message IDs currently in Mailpit (call before triggering an action)."""
    try:
        msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
        return {m["ID"] for m in msgs}
    except Exception:
        return set()


def fetch_email(to_email: str, subject_fragment: str, timeout: int = 60,
                ignore_ids=None) -> str:
    """
    Poll Mailpit until a matching email arrives; return its plain-text body.
    Pass ignore_ids=mailpit_seen_ids() before triggering an action to ensure
    only freshly delivered emails are matched (prevents false passes from
    leftover messages with the same subject).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
            for msg in msgs:
                if ignore_ids and msg["ID"] in ignore_ids:
                    continue
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
# API helpers
# ---------------------------------------------------------------------------

def api(method: str, path: str, ctx: dict, **kwargs):
    return requests.request(
        method,
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {ctx['api_key']}"},
        timeout=10,
        **kwargs,
    )


def api_get(path, ctx, params=None):
    return api("GET", path, ctx, params=params)


def api_post(path, ctx, json):
    return api("POST", path, ctx, json=json)


def api_patch(path, ctx, json):
    return api("PATCH", path, ctx, json=json)


def api_delete(path, ctx):
    return api("DELETE", path, ctx)


# ---------------------------------------------------------------------------
# Docker / management command helper
# ---------------------------------------------------------------------------

def run_cmd(*args, timeout: int = 30) -> str:
    """Run a Django management command inside the running Docker container."""
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", *args],
        capture_output=True, text=True, timeout=timeout,
    )
    assert result.returncode == 0, f"Command failed:\n{result.stderr}"
    return result.stdout


def server_today() -> str:
    """Return the server's current date as YYYY-MM-DD (may differ from host when timezones diverge)."""
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "-c",
         "from datetime import date; print(date.today().isoformat())"],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Session cookie helper (for browser-auth'd CSV downloads)
# ---------------------------------------------------------------------------

def session_cookies(driver) -> dict:
    return {c["name"]: c["value"] for c in driver.get_cookies()}
