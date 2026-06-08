"""FIDO2/WebAuthn security key: setup, login, and removal, using Chrome's
WebDriver Virtual Authenticator (no real hardware key needed for CI)."""
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.virtual_authenticator import Protocol, Transport, VirtualAuthenticatorOptions
from selenium.webdriver.support import expected_conditions as EC

from helpers import _url, fill, click, submit, wait_url, wait_text, setup_user, cleanup_user


def _add_virtual_authenticator(driver):
    options = VirtualAuthenticatorOptions(
        protocol=Protocol.CTAP2,
        transport=Transport.INTERNAL,
        has_resident_key=False,
        has_user_verification=True,
        is_user_consenting=True,
        is_user_verified=True,
    )
    driver.add_virtual_authenticator(options)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    _add_virtual_authenticator(driver)
    yield c
    driver.remove_virtual_authenticator()
    cleanup_user(c["email"])


class TestWebAuthn:

    def _register_key(self, driver, w, label="Test Security Key"):
        driver.get(_url("/webauthn/setup/"))
        fill(w, By.ID, "id_label", label)
        click(w, By.ID, "webauthn-register-btn")
        wait_text(driver, w, "Security key added")

    def test_setup_security_key(self, driver, w, ctx):
        self._register_key(driver, w)
        recovery_el = w.until(EC.presence_of_element_located((By.ID, "recovery-code")))
        ctx["recovery_code"] = recovery_el.text.strip()
        assert len(ctx["recovery_code"]) > 5
        click(w, By.CSS_SELECTOR, "a.btn")

    def test_profile_shows_security_key_as_primary(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Security Key")
        assert "Primary" in driver.page_source

    def test_login_with_security_key(self, driver, w, ctx):
        click(w, By.CSS_SELECTOR, "button[type=submit]#logout-button")
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx["password"])
        submit(w)
        wait_url(w, "/twofa/verify/")
        click(w, By.ID, "webauthn-login-btn")
        wait_url(w, "/budget/")

    def test_login_rejects_a_second_virtual_authenticator(self, driver, w, ctx):
        """A different (unregistered) authenticator must not be accepted:
        removing and re-adding the virtual authenticator simulates a
        different physical key that was never registered to this account.
        The browser itself refuses the ceremony (no matching credential for
        allowCredentials), so the client-side error fires; the request never
        reaches the server at all."""
        click(w, By.CSS_SELECTOR, "button[type=submit]#logout-button")
        driver.remove_virtual_authenticator()
        _add_virtual_authenticator(driver)
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx["password"])
        submit(w)
        wait_url(w, "/twofa/verify/")
        click(w, By.ID, "webauthn-login-btn")
        wait_text(driver, w, "We could not verify your security key")
        assert "/twofa/verify/" in driver.current_url

    def test_recovery_removes_security_key_too(self, driver, w, ctx):
        """The global recovery code must wipe a WebAuthn factor exactly like
        a TOTP factor: re-register a fresh key, log out, then recover."""
        # The rejected login above left twofa_pending_id set with no valid
        # authenticator available; start clean from the login form.
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
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Not enabled")
