"""Auth: registration, email confirmation, login, last_login/last_seen tracking."""
import subprocess
import time


import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, fill, click, wait_url, wait_text,
    fetch_email, extract_link, cleanup_user,
    register_user, PASSWORD, DOCKER_WEB,
)


def _get_feuser_field(email, field):
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c",
         f"from feusers.models import FeUser; u = FeUser.objects.get(email='{email}');"
         f" print(getattr(u, '{field}'))"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


@pytest.fixture(scope="module")
def ctx():
    """Auth tests fill this dict themselves; fixture ensures cleanup on failure."""
    c = {}
    yield c
    if "email" in c:
        cleanup_user(c["email"])


class TestAuth:

    def test_register(self, driver, w, ctx):
        result = register_user(driver, w)
        ctx.update(result)

    def test_confirm_email(self, driver, w, ctx):
        body = fetch_email(ctx["email"], "confirm")
        driver.get(extract_link(body))
        wait_text(driver, w, "confirmed")

    def test_login(self, driver, w, ctx):
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx["password"])
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        wait_url(w, "/budget/")

    def test_last_login_set(self, driver, w, ctx):
        value = _get_feuser_field(ctx["email"], "last_login")
        assert value and value != "None", "last_login must be set after login"

    def test_last_seen_set(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        time.sleep(1)
        value = _get_feuser_field(ctx["email"], "last_seen")
        assert value and value != "None", "last_seen must be set after an authenticated request"

    def test_delete_account(self, driver, w, ctx):
        """Tests UI account deletion; cleanup_user handles the case where this test fails."""
        driver.get(_url("/account/delete/"))
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
