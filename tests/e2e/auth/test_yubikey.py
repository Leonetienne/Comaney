"""YubiKey OTP second factor, see feusers/yubico_otp_service.py.

Unlike TOTP/email (deterministic local math) or WebAuthn (Chrome's Virtual
Authenticator gives a scriptable fake key), a real YubiKey OTP can only be
produced by touching a genuine physical key, and verifying one always means a
real network round trip to the configured YUBICO_SERVER - neither is
available here. So, matching how test_email_2fa.py's security tests focus on
the wrong-code path rather than needing a "real" happy path, this file covers
what's actually testable without hardware: gating (available only when
YUBICO_CLIENT_ID/YUBICO_SECRET_KEY are configured), the locally-rejected
malformed-OTP path (never reaches the network, so no flaky external
dependency either way), and the generic login/recovery wiring using a factor
row created directly via the shell. The real signed request/response
round trip itself is covered at the protocol level by
tests/unit/test_yubico_otp_service.py.

Run with (live stack at :8080 required, plus YUBICO_CLIENT_ID/YUBICO_SECRET_KEY
configured on the server):
    pytest tests/e2e/auth/test_yubikey.py -v | tee logfile.log
"""
import pytest
from selenium.webdriver.common.by import By

from bhelpers import _shell
from helpers import (
    _url, fill, submit, wait_text,
    setup_user, cleanup_user, create_confirmed_user,
    http_session, form_login, form_post,
)

FAKE_PUBLIC_ID = "ccccccvvvvvv"


def _yubico_configured() -> bool:
    return _shell(
        "from django.conf import settings; "
        "print(bool(settings.YUBICO_CLIENT_ID and settings.YUBICO_SECRET_KEY))"
    ) == "True"


def _has_yubikey_factor(email: str) -> bool:
    return _shell(
        f"from feusers.models import FeUser, YubikeyFactor; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"print(YubikeyFactor.objects.filter(feuser=u).exists())"
    ) == "True"


def _create_yubikey_factor(email: str, public_id: str = FAKE_PUBLIC_ID) -> None:
    _shell(
        f"from feusers.models import FeUser, YubikeyFactor; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"YubikeyFactor.objects.create(feuser=u, public_id='{public_id}', is_primary=True, label='Test YubiKey')"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    if not _yubico_configured():
        pytest.skip("YUBICO_CLIENT_ID/YUBICO_SECRET_KEY are not set on this server")
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestYubikeySetup:

    def test_setup_option_appears_in_dropdown(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Two-factor authentication")
        assert "/yubikey/setup/" in driver.page_source

    def test_malformed_otp_is_rejected_locally_and_creates_no_factor(self, driver, w, ctx):
        driver.get(_url("/yubikey/setup/"))
        fill(w, By.ID, "id_otp", "not-a-real-yubikey-otp")
        submit(w)
        wait_text(driver, w, "verify that YubiKey")  # avoid the apostrophe: HTML-escaped as &#x27; in page_source
        assert "/yubikey/setup/" in driver.current_url
        assert not _has_yubikey_factor(ctx["email"])


class TestYubikeyLoginWiring:
    """Confirms a YubikeyFactor is correctly wired into the generic
    login/recovery dispatch tables (see feusers/views/twofa.py's
    _LOGIN_VERIFIERS and feusers/second_factor_registry.py) with no
    yubikey-specific branch anywhere in that machinery, using a factor row
    created directly via the shell since no real key is available here."""

    def test_challenge_page_shows_the_otp_field(self):
        user = create_confirmed_user()
        try:
            _create_yubikey_factor(user["email"])
            s = http_session()
            login_resp = form_login(s, user["email"], user["password"])
            assert login_resp.status_code in (301, 302), f"password step failed: {login_resp.status_code}"
            verify_page = s.get(_url("/twofa/verify/"), timeout=10)
            assert 'name="otp"' in verify_page.text
        finally:
            cleanup_user(user["email"])

    def test_a_garbage_otp_is_rejected_at_login(self):
        user = create_confirmed_user()
        try:
            _create_yubikey_factor(user["email"])
            s = http_session()
            login_resp = form_login(s, user["email"], user["password"])
            assert login_resp.status_code in (301, 302)
            resp, _ = form_post(s, "/twofa/verify/", {"otp": "not-a-real-otp"}, csrf_path="/twofa/verify/")
            assert resp.status_code == 200, "A bad OTP must re-render the challenge, not redirect/succeed"
            assert "Verification failed" in resp.text
        finally:
            cleanup_user(user["email"])

    def test_recovery_code_removes_the_yubikey_factor_too(self):
        """The global recovery code must wipe a YubikeyFactor exactly like
        any other method (consume_recovery_code() iterates get_all_factors()
        generically)."""
        user = create_confirmed_user()
        try:
            _create_yubikey_factor(user["email"])
            s = http_session()
            login_resp = form_login(s, user["email"], user["password"])
            assert login_resp.status_code in (301, 302)
            code = _shell(
                f"from feusers.models import FeUser; "
                f"from feusers.second_factor_service import generate_recovery_code; "
                f"u = FeUser.objects.get(email='{user['email']}'); "
                f"print(generate_recovery_code(u))"
            )
            resp, _ = form_post(
                s, "/twofa/verify/recovery/", {"recovery": code}, csrf_path="/twofa/verify/recovery/",
            )
            assert resp.status_code in (301, 302), resp.text
            assert not _has_yubikey_factor(user["email"])
        finally:
            cleanup_user(user["email"])
