"""
Email change flow:
- Submit new email via profile form in the browser
- Confirmation email sent to new address
- Profile shows pending email before confirmation
- Confirmation link updates the account email (verified in browser)
- Second visit to used token returns 404 (no server error)
"""
import time
import uuid

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, fill,
    fetch_email, extract_link, mailpit_seen_ids,
    setup_user, cleanup_user, PASSWORD,
)


def _submit_form(driver, action_value):
    driver.execute_script(
        f"document.querySelector(\"input[name='action'][value='{action_value}']\").closest('form').submit()"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestEmailChange:

    def test_submit_email_change(self, driver, w, ctx):
        new_email = f"changed.{uuid.uuid4().hex[:6]}@example.com"
        ctx["pending_email"] = new_email
        seen = mailpit_seen_ids()

        driver.get(_url("/profile/"))
        time.sleep(1)
        fill(w, By.ID, "id_email", new_email)
        fill(w, By.ID, "id_password", PASSWORD)
        _submit_form(driver, "email")
        time.sleep(2)

        assert "Confirmation sent" in driver.page_source, (
            "Profile page must show confirmation-sent message after submission"
        )

        body = fetch_email(new_email, "Confirm", timeout=30, ignore_ids=seen)
        ctx["email_change_link"] = extract_link(body)

    def test_profile_shows_pending_confirmation_notice(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        assert ctx["pending_email"] in driver.page_source

    def test_confirm_link_updates_email(self, driver, w, ctx):
        driver.get(ctx["email_change_link"])
        time.sleep(2)
        assert "Email updated" in driver.page_source
        ctx["email"] = ctx["pending_email"]

    def test_new_email_shown_on_profile(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        assert ctx["email"] in driver.page_source

    def test_used_token_does_not_cause_server_error(self, driver, w, ctx):
        driver.get(ctx["email_change_link"])
        time.sleep(1)
        assert "Server Error" not in driver.page_source
        assert "500" not in driver.title
