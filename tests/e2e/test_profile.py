"""Profile update, API key generation, and API key revocation."""
import time

import requests
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, click, wait_url, wait_text, fill, BASE_URL,
    setup_user, cleanup_user,
)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestProfile:

    def test_update_profile(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Personal info")
        fill(w, By.ID, "id_currency", "$")
        driver.execute_script(
            "document.querySelector(\"input[name='action'][value='profile']\").closest('form').submit()")
        wait_url(w, "/profile/")
        wait_text(driver, w, "Saved.")

    def test_generate_api_key(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        click(w, By.XPATH, "//form[contains(@action,'api-key/generate')]//button")
        wait_url(w, "/profile/")
        key_el = w.until(EC.presence_of_element_located((By.ID, "api-key-display")))
        new_key = key_el.get_attribute("value")
        assert len(new_key) > 10
        ctx["api_key"] = new_key

    def test_api_key_authenticates(self, driver, w, ctx):
        time.sleep(1)
        resp = requests.get(
            f"{BASE_URL}/api/v1/account/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == ctx["email"]

    def test_revoke_api_key(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        click(w, By.XPATH, "//form[contains(@action,'api-key/revoke')]//button")
        wait_url(w, "/profile/")
        time.sleep(1)
        resp = requests.get(
            f"{BASE_URL}/api/v1/account/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 401, "Revoked key must return 401"
        # Re-generate so teardown (cleanup_user) doesn't need an API key
        from helpers import get_api_key
        ctx["api_key"] = get_api_key(driver, w)
