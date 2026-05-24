"""
Advanced profile features:
- AI settings form: save anthropic API key and custom instructions via browser
- Email notifications toggle via profile form checkbox in browser
- Password change via profile form in browser (old password rejected, new accepted)
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, fill, browser_login,
    api_get, api_patch,
    setup_user, cleanup_user, PASSWORD,
)

NEW_PASSWORD = "R41n3RWlnKl3R"


def _submit_form(driver, action_value):
    """Submit the profile form whose hidden action input has the given value."""
    driver.execute_script(
        f"document.querySelector(\"input[name='action'][value='{action_value}']\").closest('form').submit()"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestAISettings:

    def test_save_anthropic_api_key(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        fill(w, By.ID, "id_anthropic_api_key", "sk-ant-api03-testkey5678")
        _submit_form(driver, "ai")
        time.sleep(2)
        assert "Saved." in driver.page_source

    def test_masked_key_shown_in_form(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        value = driver.find_element(By.ID, "id_anthropic_api_key").get_attribute("value")
        assert value.startswith("****"), "Key must be masked in the form field"
        assert value.endswith("5678"), "Last 4 chars must be visible"

    def test_save_custom_instructions(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        fill(w, By.ID, "id_ai_custom_instructions",
             "Always use category Groceries for supermarket purchases.")
        _submit_form(driver, "ai")
        time.sleep(2)
        assert "Saved." in driver.page_source

    def test_custom_instructions_round_trip(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        value = driver.find_element(By.ID, "id_ai_custom_instructions").get_attribute("value")
        assert "Groceries" in value

    def test_clear_api_key(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        driver.find_element(By.ID, "id_anthropic_api_key").clear()
        fill(w, By.ID, "id_ai_custom_instructions", "")
        _submit_form(driver, "ai")
        time.sleep(2)
        assert "Saved." in driver.page_source


class TestEmailNotificationsToggle:

    def test_disable_via_notifications_form(self, driver, w, ctx):
        api_patch("/api/v1/account/", ctx, json={"email_notifications": True})

        driver.get(_url("/profile/"))
        time.sleep(1)
        checkbox = driver.find_element(By.ID, "id_email_notifications")
        if checkbox.is_selected():
            checkbox.click()
            time.sleep(0.2)

        _submit_form(driver, "notifications")
        time.sleep(2)
        assert "Saved." in driver.page_source

        time.sleep(1)
        assert api_get("/api/v1/account/", ctx).json()["email_notifications"] is False

    def test_enable_via_notifications_form(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        checkbox = driver.find_element(By.ID, "id_email_notifications")
        if not checkbox.is_selected():
            checkbox.click()
            time.sleep(0.2)

        _submit_form(driver, "notifications")
        time.sleep(2)
        assert "Saved." in driver.page_source

        time.sleep(1)
        assert api_get("/api/v1/account/", ctx).json()["email_notifications"] is True


class TestPasswordChange:

    def test_change_password(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        fill(w, By.ID, "id_current_password", PASSWORD)
        fill(w, By.ID, "id_new_password", NEW_PASSWORD)
        fill(w, By.ID, "id_new_password_confirm", NEW_PASSWORD)
        _submit_form(driver, "password")
        time.sleep(2)
        assert "Password updated." in driver.page_source

    def test_old_password_rejected_after_change(self, driver, w, ctx):
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        time.sleep(1)
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        time.sleep(1)
        assert "/budget/" not in driver.current_url

    def test_new_password_accepted(self, driver, w, ctx):
        browser_login(driver, w, ctx["email"], NEW_PASSWORD)
        ctx["password"] = NEW_PASSWORD

    def test_wrong_current_password_shows_error(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        fill(w, By.ID, "id_current_password", "wrongpassword")
        fill(w, By.ID, "id_new_password", "something99!")
        fill(w, By.ID, "id_new_password_confirm", "something99!")
        _submit_form(driver, "password")
        time.sleep(2)
        assert "Incorrect password" in driver.page_source

    def test_mismatched_passwords_show_error(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        fill(w, By.ID, "id_current_password", NEW_PASSWORD)
        fill(w, By.ID, "id_new_password", "Mismatch1!")
        fill(w, By.ID, "id_new_password_confirm", "Mismatch2!")
        _submit_form(driver, "password")
        time.sleep(2)
        assert "do not match" in driver.page_source.lower()
