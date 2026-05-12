"""Two-factor authentication: setup, login with code, recovery code, disable."""
import pyotp
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, fill, click, submit, wait_url, wait_text,
    browser_login, setup_user, cleanup_user,
)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestTotp:

    def _setup_totp(self, driver, w, ctx):
        """Enable TOTP and store secret + recovery code in ctx."""
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        ctx["totp_secret"] = secret_el.text.strip()
        fill(w, By.ID, "id_code", pyotp.TOTP(ctx["totp_secret"]).now())
        submit(w)
        recovery_el = w.until(EC.presence_of_element_located((By.ID, "recovery-code")))
        ctx["recovery_code"] = recovery_el.text.strip()
        click(w, By.CSS_SELECTOR, "a.btn")

    def _login_with_totp(self, driver, w, ctx):
        """Log out, then log back in with a TOTP code."""
        click(w, By.CSS_SELECTOR, "button[type=submit]#logout-button")
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx["password"])
        submit(w)
        wait_url(w, "/totp/verify/")
        fill(w, By.ID, "id_code", pyotp.TOTP(ctx["totp_secret"]).now())
        submit(w)
        wait_url(w, "/budget/")

    def test_setup_2fa(self, driver, w, ctx):
        self._setup_totp(driver, w, ctx)
        assert len(ctx["totp_secret"]) > 10
        assert len(ctx["recovery_code"]) > 5

    def test_login_with_totp(self, driver, w, ctx):
        self._login_with_totp(driver, w, ctx)

    def test_disable_2fa(self, driver, w, ctx):
        driver.get(_url("/totp/disable/"))
        fill(w, By.ID, "id_code", pyotp.TOTP(ctx["totp_secret"]).now())
        submit(w)
        wait_url(w, "/profile/")
        wait_text(driver, w, "Not enabled")

    def test_setup_and_login_with_recovery(self, driver, w, ctx):
        """Set up 2FA again, then log in using the recovery code."""
        self._setup_totp(driver, w, ctx)
        # Log out
        click(w, By.CSS_SELECTOR, "button[type=submit]#logout-button")
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx["password"])
        submit(w)
        wait_url(w, "/totp/verify/")
        click(w, By.LINK_TEXT, "Lost access to your app? Use a recovery code")
        wait_url(w, "/totp/verify/recovery/")
        fill(w, By.ID, "id_recovery", ctx["recovery_code"])
        submit(w)
        wait_url(w, "/")

    def test_disable_2fa_with_recovery(self, driver, w, ctx):
        """Set up 2FA and disable it using a recovery code."""
        self._setup_totp(driver, w, ctx)
        driver.get(_url("/totp/disable/"))
        click(w, By.LINK_TEXT, "Lost access to your app? Use a recovery code")
        wait_url(w, "/totp/disable/?recovery=1")
        fill(w, By.ID, "id_recovery", ctx["recovery_code"])
        submit(w)
        wait_url(w, "/profile/")
        wait_text(driver, w, "Not enabled")
