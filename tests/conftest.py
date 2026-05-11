"""
Pytest session fixtures for tests_new.

Each test file defines its own module-scoped ctx fixture that creates and
destroys a user.  This file only provides the shared browser (driver, w)
and the reachability guard.
"""
import subprocess
import tempfile

import pytest
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from helpers import BASE_URL, MAILPIT_API, DOCKER_WEB, TIMEOUT


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
