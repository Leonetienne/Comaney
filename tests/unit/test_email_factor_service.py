"""
Unit tests for the TOTP-shaped parts of feusers/email_factor_service.py: the
generated code itself is never stored (DB or cache), only ever recomputed
from a secret + the current time, so that math is what needs covering here.
Sending, throttling, and the full setup/login flow all touch Django settings,
the cache, and the DB, so those are covered by e2e tests instead (see
tests/e2e/auth/test_email_2fa.py), matching this project's convention that
TOTP/2FA behavior needing a database goes there.

No Django/DB required. Run with:
    venv/bin/pytest tests/unit/test_email_factor_service.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pyotp

from feusers.email_factor_service import CODE_INTERVAL, generate_secret, verify_code


def test_generate_secret_is_a_valid_base32_totp_secret():
    secret = generate_secret()
    # Raises if not valid base32; also confirms it's usable as a TOTP secret.
    pyotp.TOTP(secret).now()


def test_verify_code_accepts_the_current_code():
    secret = generate_secret()
    current = pyotp.TOTP(secret, interval=CODE_INTERVAL).now()
    assert verify_code(secret, current) is True


def test_verify_code_rejects_a_wrong_code():
    secret = generate_secret()
    current = pyotp.TOTP(secret, interval=CODE_INTERVAL).now()
    wrong = "".join("1" if d != "1" else "2" for d in current)
    assert verify_code(secret, wrong) is False


def test_verify_code_rejects_a_code_from_a_different_secret():
    secret_a = generate_secret()
    secret_b = generate_secret()
    code_from_b = pyotp.TOTP(secret_b, interval=CODE_INTERVAL).now()
    assert verify_code(secret_a, code_from_b) is False


def test_code_interval_is_longer_than_a_standard_authenticator_step():
    # A plain 30s TOTP step would routinely expire before an email arrives
    # and is read; this must use something much longer.
    assert CODE_INTERVAL > 30
