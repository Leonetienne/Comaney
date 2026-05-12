"""
Password reset full flow:
- Forgot password form sends email
- Reset link loads the reset form
- New password is accepted and old password is rejected
- Used token is invalidated after reset
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, fill, click, mailpit_seen_ids,
    fetch_email, extract_link, setup_user, cleanup_user,
    PASSWORD,
)

NEW_PASSWORD = "R41n3RWlnKl3R"


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    # Password-reset tests start from an unauthenticated state.
    driver.delete_all_cookies()
    driver.execute_script("sessionStorage.clear(); localStorage.clear();")
    yield c
    cleanup_user(c["email"])


class TestPasswordReset:

    def test_forgot_form_sends_email(self, driver, w, ctx):
        seen = mailpit_seen_ids()
        driver.get(_url("/password-forgot/"))
        time.sleep(1)
        fill(w, By.ID, "id_email", ctx["email"])
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
        assert "sent" in driver.current_url or "password-forgot" in driver.current_url
        body = fetch_email(ctx["email"], "Reset your password", timeout=30, ignore_ids=seen)
        ctx["reset_link"] = extract_link(body)

    def test_reset_page_renders_form(self, driver, w, ctx):
        driver.get(ctx["reset_link"])
        time.sleep(1)
        assert driver.find_element(By.ID, "id_password")

    def test_set_new_password(self, driver, w, ctx):
        driver.get(ctx["reset_link"])
        time.sleep(1)
        fill(w, By.ID, "id_password", NEW_PASSWORD)
        fill(w, By.ID, "id_password_confirm", NEW_PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
        assert "done" in driver.current_url

    def test_old_password_rejected_after_reset(self, driver, w, ctx):
        driver.get(_url("/login/"))
        time.sleep(1)
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(1)
        assert "/budget/" not in driver.current_url

    def test_new_password_accepted(self, driver, w, ctx):
        driver.get(_url("/login/"))
        time.sleep(1)
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", NEW_PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
        assert "/budget/" in driver.current_url
        ctx["password"] = NEW_PASSWORD

    def test_used_token_is_invalidated(self, driver, w, ctx):
        driver.get(ctx["reset_link"])
        time.sleep(1)
        src = driver.page_source.lower()
        assert "invalid" in src or "expired" in src or "not found" in src
