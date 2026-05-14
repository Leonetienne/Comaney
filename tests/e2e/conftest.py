"""
Pytest session fixtures for tests_new.

Each test file defines its own module-scoped ctx fixture that creates and
destroys a user.  This file only provides the shared browser (driver, w)
and the reachability guard.
"""
import subprocess
import sys
import os
import tempfile

# Ensure tests/e2e/ is on sys.path regardless of where pytest is invoked from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait

from helpers import BASE_URL, MAILPIT_API, DOCKER_WEB, TIMEOUT

# On macOS, native Selenium clicks are silently dropped when the browser window
# is in the background. Patch WebElement.click to always dispatch via JS so
# tests are focus-independent.
_orig_click = WebElement.click

def _js_click(self):
    try:
        if self.tag_name.lower() == "option":
            # Clicking <option> via JS doesn't fire the change event on the
            # parent <select>. Set the value and dispatch change explicitly.
            self._parent.execute_script("""
                var opt = arguments[0];
                var sel = opt.closest('select');
                if (sel) {
                    sel.value = opt.value;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                }
            """, self)
        else:
            # Use setTimeout to defer the click so execute_script returns before
            # any resulting navigation begins. A direct .click() call causes
            # ChromeDriver to block execute_script until the new page loads,
            # which can exceed urllib3's read timeout and raise ReadTimeoutError.
            self._parent.execute_script(
                "var el = arguments[0]; setTimeout(function(){ el.click(); }, 0);",
                self,
            )
    except Exception:
        _orig_click(self)

WebElement.click = _js_click


def pytest_configure(config):
    try:
        requests.get(BASE_URL, timeout=5)
    except Exception:
        pytest.exit(f"\nABORT: App not reachable at {BASE_URL}\n", returncode=1)

    try:
        result = subprocess.run(
            ["docker", "exec", DOCKER_WEB, "python", "-c",
             "import os\n"
             "print(os.environ.get('DISABLE_EMAILING','').upper())\n"
             "print(os.environ.get('EMAIL_HOST',''))"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        lines = result.stdout.splitlines()
        if len(lines) < 2:
            return
        disable_emailing = lines[0].strip()
        email_host       = lines[1].strip()
    except Exception:
        return

    if disable_emailing in ("1", "TRUE", "YES"):
        pytest.exit(
            "\nABORT: DISABLE_EMAILING is set. Configure Mailpit first.\n",
            returncode=1,
        )
    if email_host.lower() != "mailpit":
        pytest.exit(
            f"\nABORT: EMAIL_HOST is '{email_host}', expected 'mailpit'.\n",
            returncode=1,
        )


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
