"""Renaming a 2FA factor's name in place (profile page, .ct-name pattern), and
using the per-factor "Test" page to verify which physical key or
authenticator entry a factor actually corresponds to, without logging out."""
import time

import pyotp
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.virtual_authenticator import Protocol, Transport, VirtualAuthenticatorOptions
from selenium.webdriver.support import expected_conditions as EC

from helpers import _url, fill, click, submit, wait_text, setup_user, cleanup_user


def _add_virtual_authenticator(driver):
    options = VirtualAuthenticatorOptions(
        protocol=Protocol.CTAP2, transport=Transport.INTERNAL,
        has_resident_key=False, has_user_verification=True,
        is_user_consenting=True, is_user_verified=True,
    )
    driver.add_virtual_authenticator(options)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    _add_virtual_authenticator(driver)
    yield c
    driver.remove_virtual_authenticator()
    cleanup_user(c["email"])


def _click_and_type_rename(driver, name_selector, new_value):
    driver.execute_script(
        f"var el=document.querySelector('{name_selector}');"
        "el.scrollIntoView({block:'center'}); el.click();"
    )
    time.sleep(0.5)
    driver.execute_script(
        f"var inp=document.querySelector('{name_selector} .ct-name-input');"
        f"inp.value={new_value!r};"
        "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));"
    )
    time.sleep(0.5)


class TestFactorRenameAndTest:

    def test_setup_totp_with_label(self, driver, w, ctx):
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        ctx["totp_secret"] = secret_el.text.strip()
        fill(w, By.ID, "id_label", "Initial Name")
        fill(w, By.ID, "id_code", pyotp.TOTP(ctx["totp_secret"]).now())
        submit(w)
        w.until(EC.presence_of_element_located((By.ID, "recovery-code")))
        click(w, By.CSS_SELECTOR, "a.btn")

    def test_rename_totp_factor_in_place(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Initial Name")
        _click_and_type_rename(driver, ".twofa-factor-label", "key_deskdrawer")
        driver.get(_url("/profile/"))
        wait_text(driver, w, "key_deskdrawer")
        assert "Initial Name" not in driver.page_source

    def test_renaming_to_blank_is_ignored(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        _click_and_type_rename(driver, ".twofa-factor-label", "   ")
        assert "key_deskdrawer" in driver.page_source

    def test_test_button_with_correct_code_matches(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        click(w, By.CSS_SELECTOR, "#section-2fa a.btn-secondary[href*='/test/']")
        wait_text(driver, w, 'Test "key_deskdrawer"')
        fill(w, By.ID, "id_code", pyotp.TOTP(ctx["totp_secret"]).now())
        submit(w)
        wait_text(driver, w, "Match!")

    def test_test_button_with_wrong_code_does_not_match(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        click(w, By.CSS_SELECTOR, "#section-2fa a.btn-secondary[href*='/test/']")
        fill(w, By.ID, "id_code", "000000")
        submit(w)
        wait_text(driver, w, "No match")

    def test_setup_webauthn_key(self, driver, w, ctx):
        driver.get(_url("/webauthn/setup/"))
        fill(w, By.ID, "id_label", "YubiKey A")
        click(w, By.ID, "webauthn-register-btn")
        wait_text(driver, w, "Security key added")
        click(w, By.CSS_SELECTOR, "a.btn")

    def _webauthn_row(self, driver):
        rows = driver.find_elements(By.CSS_SELECTOR, ".twofa-factor-row")
        return next(r for r in rows if "Security Key" in r.text)

    def test_rename_webauthn_factor_too(self, driver, w, ctx):
        """Rename must work for any registered method, not just TOTP."""
        driver.get(_url("/profile/"))
        wait_text(driver, w, "YubiKey A")
        row = self._webauthn_row(driver)
        row.find_element(By.CSS_SELECTOR, ".twofa-factor-label").click()
        time.sleep(0.5)
        driver.execute_script(
            "var inp=document.querySelector('.twofa-factor-row .ct-name-input');"
            "inp.value='yubikey_serial_1234';"
            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));"
        )
        time.sleep(0.5)
        driver.get(_url("/profile/"))
        wait_text(driver, w, "yubikey_serial_1234")

    def test_webauthn_test_button_matches_the_registered_key(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "yubikey_serial_1234")
        row = self._webauthn_row(driver)
        row.find_element(By.CSS_SELECTOR, "a.btn-secondary[href*='/test/']").click()
        time.sleep(0.5)
        click(w, By.ID, "webauthn-login-btn")
        wait_text(driver, w, "Match!")

    def test_webauthn_test_button_rejects_a_different_virtual_authenticator(self, driver, w, ctx):
        """A different (unregistered) authenticator must not be accepted:
        removing and re-adding the virtual authenticator simulates a
        different physical key that was never registered to this account."""
        driver.remove_virtual_authenticator()
        _add_virtual_authenticator(driver)
        driver.get(_url("/profile/"))
        row = self._webauthn_row(driver)
        row.find_element(By.CSS_SELECTOR, "a.btn-secondary[href*='/test/']").click()
        time.sleep(0.5)
        click(w, By.ID, "webauthn-login-btn")
        wait_text(driver, w, "We could not verify your security key")
