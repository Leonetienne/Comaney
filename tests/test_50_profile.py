"""Profile update and API key lifecycle."""
import time
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from conftest import _url, fill, click, wait_url, wait_text, BASE_URL, PASSWORD


class TestProfile:

    def test_17_update_profile(self, driver, w, ctx):
        time.sleep(1)
        driver.get(_url("/profile/"))
        time.sleep(1)
        wait_text(driver, w, "Personal info")
        fill(w, By.ID, "id_currency", "$")
        driver.execute_script(
            "document.querySelector(\"input[name='action'][value='profile']\").closest('form').submit()"
        )
        time.sleep(1)
        wait_url(w, "/profile/")
        wait_text(driver, w, "Saved.")

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
