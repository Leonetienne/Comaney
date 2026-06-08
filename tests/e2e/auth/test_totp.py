"""Two-factor authentication: TOTP setup, login with code, recovery code, removal."""
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

    def _setup_totp(self, driver, w, ctx, label=""):
        """Enable TOTP and store secret + recovery code in ctx."""
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        ctx["totp_secret"] = secret_el.text.strip()
        if label:
            fill(w, By.ID, "id_label", label)
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
        wait_url(w, "/twofa/verify/")
        fill(w, By.ID, "id_code", pyotp.TOTP(ctx["totp_secret"]).now())
        submit(w)
        wait_url(w, "/budget/")

    def test_setup_2fa(self, driver, w, ctx):
        self._setup_totp(driver, w, ctx)
        assert len(ctx["totp_secret"]) > 10
        assert len(ctx["recovery_code"]) > 5

    def test_setup_shows_primary_checkbox_disabled_for_first_factor(self, driver, w, ctx):
        # Already set up above; re-visit disable-then-resetup to inspect the
        # very first factor's checkbox state fresh.
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Two-factor authentication")
        assert "Is primary" in driver.page_source

    def test_login_with_totp(self, driver, w, ctx):
        self._login_with_totp(driver, w, ctx)

    def test_profile_shows_enabled_and_factor_row(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Authenticator App")
        assert "Not enabled" not in driver.page_source

    def test_remove_only_factor_shows_solo_confirmation_then_disables(self, driver, w, ctx):
        """Removing the sole factor needs no other factor to confirm with,
        but a plain GET must not delete it outright: a confirm page with an
        explicit POST button is required first."""
        driver.get(_url("/profile/"))
        click(w, By.CSS_SELECTOR, "#section-2fa a.btn-danger")
        wait_text(driver, w, "turns two-factor authentication off entirely")
        assert "/profile/" not in driver.current_url
        submit(w)
        wait_url(w, "/profile/")
        wait_text(driver, w, "Not enabled")

    def test_setup_and_login_with_recovery(self, driver, w, ctx):
        """Set up 2FA again, then log in using the global recovery code."""
        self._setup_totp(driver, w, ctx)
        click(w, By.CSS_SELECTOR, "button[type=submit]#logout-button")
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx["password"])
        submit(w)
        wait_url(w, "/twofa/verify/")
        click(w, By.LINK_TEXT, "Lost access? Use a recovery code")
        wait_url(w, "/twofa/verify/recovery/")
        fill(w, By.ID, "id_recovery", ctx["recovery_code"])
        submit(w)
        wait_url(w, "/")

    def test_recovery_removed_the_factor(self, driver, w, ctx):
        """Using the recovery code must have wiped the TOTP factor too."""
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Not enabled")

    def test_second_factor_setup_does_not_show_a_new_recovery_code(self, driver, w, ctx):
        """The first factor after the recovery-code wipe is a fresh '0->1'
        transition, so it gets a brand-new recovery code shown once; adding
        a second factor after that must not show another one."""
        self._setup_totp(driver, w, ctx)  # first factor again (post-wipe)
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        second_secret = secret_el.text.strip()
        fill(w, By.ID, "id_code", pyotp.TOTP(second_secret).now())
        submit(w)
        wait_text(driver, w, "Authenticator app added")
        assert "id=\"recovery-code\"" not in driver.page_source

    def test_custom_labels_distinguish_multiple_totp_factors(self, driver, w, ctx):
        """Two TOTP factors on the same account must be told apart by their
        user-chosen names, not both showing as indistinguishable
        "Authenticator App" rows."""
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        third_secret = secret_el.text.strip()
        fill(w, By.ID, "id_label", "key_deskdrawer")
        fill(w, By.ID, "id_code", pyotp.TOTP(third_secret).now())
        submit(w)
        wait_text(driver, w, "Authenticator app added")
        click(w, By.CSS_SELECTOR, "a.btn")

        driver.get(_url("/profile/"))
        wait_text(driver, w, "key_deskdrawer")
        rows = driver.find_elements(By.CSS_SELECTOR, ".twofa-factor-row")
        labels = [r.find_element(By.CSS_SELECTOR, ".twofa-factor-label").text for r in rows]
        assert labels.count("key_deskdrawer") == 1, f"custom label not uniquely shown: {labels}"
