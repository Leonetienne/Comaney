"""Cross-cutting multi-factor behavior: primary selection, method switching at
login, and removing one factor by confirming with a different one."""
import pyotp
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.virtual_authenticator import Protocol, Transport, VirtualAuthenticatorOptions
from selenium.webdriver.support import expected_conditions as EC

from helpers import _url, fill, click, submit, wait_url, wait_text, setup_user, cleanup_user


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    options = VirtualAuthenticatorOptions(
        protocol=Protocol.CTAP2, transport=Transport.INTERNAL,
        has_resident_key=False, has_user_verification=True,
        is_user_consenting=True, is_user_verified=True,
    )
    driver.add_virtual_authenticator(options)
    yield c
    driver.remove_virtual_authenticator()
    cleanup_user(c["email"])


class TestMultiFactor:

    def test_totp_is_primary_by_default_as_first_factor(self, driver, w, ctx):
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        ctx["totp_secret"] = secret_el.text.strip()
        # First-ever factor: the primary checkbox is pre-checked and disabled.
        assert not driver.find_element(By.CSS_SELECTOR, "input[name=make_primary][type=checkbox]").is_enabled()
        fill(w, By.ID, "id_code", pyotp.TOTP(ctx["totp_secret"]).now())
        submit(w)
        recovery_el = w.until(EC.presence_of_element_located((By.ID, "recovery-code")))
        ctx["recovery_code"] = recovery_el.text.strip()
        click(w, By.CSS_SELECTOR, "a.btn")

    def test_adding_webauthn_without_checkbox_keeps_totp_primary(self, driver, w, ctx):
        driver.get(_url("/webauthn/setup/"))
        fill(w, By.ID, "id_label", "Backup Key")
        # Leave "use as primary" unchecked.
        click(w, By.ID, "webauthn-register-btn")
        wait_text(driver, w, "Security key added")
        assert "id=\"recovery-code\"" not in driver.page_source
        click(w, By.CSS_SELECTOR, "a.btn")

        driver.get(_url("/profile/"))
        wait_text(driver, w, "Backup Key")
        rows = driver.find_elements(By.CSS_SELECTOR, ".twofa-factor-row")
        assert len(rows) == 2
        primary_rows = [r for r in rows if "Is primary" in r.text]
        assert len(primary_rows) == 1
        assert "Authenticator App" in primary_rows[0].text

    def test_login_shows_primary_first_with_switch_option(self, driver, w, ctx):
        click(w, By.CSS_SELECTOR, "button[type=submit]#sidebar-logout-button, button[type=submit]#logout-button")
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx["password"])
        submit(w)
        wait_url(w, "/twofa/verify/")
        # Primary (TOTP) challenge is shown directly.
        assert driver.find_elements(By.ID, "id_code")
        assert "Try a different method" in driver.page_source

    def test_switching_method_logs_in_with_webauthn_instead(self, driver, w, ctx):
        click(w, By.CSS_SELECTOR, ".method-dropdown-toggle")
        click(w, By.CSS_SELECTOR, ".method-dropdown-item")
        wait_text(driver, w, "Use security key")
        click(w, By.ID, "webauthn-login-btn")
        wait_url(w, "/budget/")

    def test_set_webauthn_as_primary(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Backup Key")
        rows = driver.find_elements(By.CSS_SELECTOR, ".twofa-factor-row")
        webauthn_row = next(r for r in rows if "Security Key" in r.text)
        webauthn_row.find_element(By.CSS_SELECTOR, "form button[type=submit]").click()
        wait_url(w, "/profile/")
        wait_text(driver, w, "Backup Key")
        rows = driver.find_elements(By.CSS_SELECTOR, ".twofa-factor-row")
        primary_rows = [r for r in rows if "Is primary" in r.text]
        assert len(primary_rows) == 1
        assert "Security Key" in primary_rows[0].text

    def test_remove_totp_requires_confirming_with_webauthn(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        rows = driver.find_elements(By.CSS_SELECTOR, ".twofa-factor-row")
        totp_row = next(r for r in rows if "Authenticator App" in r.text)
        totp_row.find_element(By.CSS_SELECTOR, "a.btn-danger").click()
        wait_text(driver, w, "Confirming with")
        assert "Security Key" in driver.page_source
        click(w, By.ID, "webauthn-login-btn")
        wait_url(w, "/profile/")
        rows = driver.find_elements(By.CSS_SELECTOR, ".twofa-factor-row")
        assert len(rows) == 1
        assert "Security Key" in rows[0].text
        assert "Is primary" in rows[0].text
