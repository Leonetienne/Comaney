"""Demo accounts must never be able to set up, remove, or regenerate a
second factor: 2FA setup is on the hard-blocked list for is_demo=True users
(see CLAUDE.md), both server-side and in the UI."""
import subprocess
import time
import uuid

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import _url, fill, click, wait_text, cleanup_user, DOCKER_WEB, PASSWORD
from bhelpers import _shell


def _demo_users_enabled() -> bool:
    return _shell("from django.conf import settings; print(settings.ENABLE_DEMO_USERS)") == "True"


@pytest.fixture(scope="module")
def demo_ctx(driver, w):
    if not _demo_users_enabled():
        pytest.skip("ENABLE_DEMO_USERS is not set on this server")

    email = f"sel.demo.{uuid.uuid4().hex[:8]}@example.com"
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py",
         "create_user", email, "-p", PASSWORD, "--demo"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, f"create_user --demo failed:\n{result.stderr}"

    driver.delete_all_cookies()
    driver.execute_script("sessionStorage.clear(); localStorage.clear();")
    driver.get(_url("/login/"))
    fill(w, By.ID, "id_email", email)
    fill(w, By.ID, "id_password", PASSWORD)
    click(w, By.CSS_SELECTOR, "button[type=submit]")
    time.sleep(2)
    if "/demo-banner/" in driver.current_url:
        click(w, By.ID, "btn-demo-accept")
        time.sleep(2)

    yield {"email": email, "password": PASSWORD}
    cleanup_user(email)


class TestDemoBlocked:

    def test_profile_shows_disabled_button(self, driver, w, demo_ctx):
        # profile.html collapses the per-method "Add ..." buttons into a
        # single "Add new second factor" dropdown toggle; for a demo account
        # it must render as one disabled button with no working dropdown.
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Two-factor authentication")
        add_btn = driver.find_element(By.XPATH, "//button[contains(.,'Add new second factor')]")
        assert not add_btn.is_enabled()

    def test_totp_setup_view_redirects_away(self, driver, w, demo_ctx):
        driver.get(_url("/totp/setup/"))
        wait_text(driver, w, "Two-factor authentication")
        assert "/totp/setup/" not in driver.current_url

    def test_webauthn_setup_view_redirects_away(self, driver, w, demo_ctx):
        driver.get(_url("/webauthn/setup/"))
        wait_text(driver, w, "Two-factor authentication")
        assert "/webauthn/setup/" not in driver.current_url

    def test_email_factor_setup_view_redirects_away(self, driver, w, demo_ctx):
        driver.get(_url("/email-2fa/setup/"))
        wait_text(driver, w, "Two-factor authentication")
        assert "/email-2fa/setup/" not in driver.current_url

    def test_yubikey_setup_view_redirects_away(self, driver, w, demo_ctx):
        driver.get(_url("/yubikey/setup/"))
        wait_text(driver, w, "Two-factor authentication")
        assert "/yubikey/setup/" not in driver.current_url

    def test_email_send_code_endpoint_has_nothing_to_send_for_demo(self, driver, w, demo_ctx):
        # Demo users can never reach a state with a persisted or mid-setup
        # EmailFactor (setup itself is blocked above), so the shared
        # send-code endpoint must find nothing to act on for them.
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        csrftoken = cookies.get("csrftoken", "")
        resp = requests.post(
            _url("/email-2fa/send-code/"),
            cookies=cookies,
            headers={"X-CSRFToken": csrftoken, "Referer": _url("/profile/")},
            timeout=10,
        )
        assert resp.status_code == 400

    def test_recovery_regenerate_view_redirects_away(self, driver, w, demo_ctx):
        driver.get(_url("/twofa/recovery/regenerate/"))
        wait_text(driver, w, "Two-factor authentication")
        assert "/twofa/recovery/regenerate/" not in driver.current_url
