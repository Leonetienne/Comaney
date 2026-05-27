"""
Regression test for TICKET-05 — TOTP recovery-code verification has no rate limit.

`totp_verify` (the 6-digit OTP step) is rate limited, but its sibling
`totp_verify_recovery` — which accepts the account recovery code to bypass 2FA and
log in — has no limiter at all. An attacker who already knows the password (the
recovery step is only reachable after the password is verified, i.e. once
`totp_pending_id` is set) can submit recovery codes as fast as they like.

This test sets up a 2FA-enabled account, reaches the recovery step, then submits a
stream of wrong recovery codes and asserts a throttle eventually kicks in.

EXPECTED TO FAIL until the recovery path shares the "totp" limiter: today every
attempt is evaluated and no lockout message ever appears.

Run with (live stack at :8080 required):
    pytest tests/e2e/auth/test_totp_recovery_rate_limit.py -sxv | tee logfile.log
"""
import pytest

from helpers import _url, http_session, form_login, create_confirmed_user, cleanup_user
from bhelpers import _shell

THROTTLE_MSG = "Too many failed attempts"
RECOVERY_PATH = "/totp/verify/recovery/"


@pytest.fixture(scope="module")
def totp_user():
    u = create_confirmed_user()
    # Enable 2FA directly. The recovery hash is set to a known code we will never
    # submit, so every attempt below is a genuine miss.
    _shell(
        f"import hashlib; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{u['email']}'); "
        f"u.totp_enabled = True; u.totp_secret = 'JBSWY3DPEHPK3PXP'; "
        f"u.totp_recovery_hash = hashlib.sha256('REALCODE01'.encode()).hexdigest(); "
        f"u.save(update_fields=['totp_enabled', 'totp_secret', 'totp_recovery_hash'])"
    )
    yield u
    cleanup_user(u["email"])


def _reach_recovery_step(session, user) -> None:
    """Log in with the correct password so the session holds totp_pending_id,
    which unlocks the recovery-verification endpoint."""
    resp = form_login(session, user["email"], user["password"])
    assert resp.status_code in (301, 302), f"password step failed: {resp.status_code}"


def _submit_wrong_recovery(session, code: str):
    session.get(_url(RECOVERY_PATH), timeout=10)
    csrf = session.cookies.get("csrftoken", "")
    return session.post(
        _url(RECOVERY_PATH),
        data={"csrfmiddlewaretoken": csrf, "recovery": code},
        headers={"Referer": _url(RECOVERY_PATH)},
        allow_redirects=False, timeout=10,
    )


class TestTotpRecoveryRateLimit:

    def test_recovery_bruteforce_is_throttled(self, totp_user):
        s = http_session()
        _reach_recovery_step(s, totp_user)

        throttled = False
        for i in range(12):
            resp = _submit_wrong_recovery(s, f"WRONG{i:05d}")
            # Once the session drops totp_pending_id the endpoint redirects to
            # login; a throttle must engage before that / instead of endless tries.
            if resp.status_code in (301, 302):
                continue
            if THROTTLE_MSG in resp.text:
                throttled = True
                break

        assert throttled, (
            "Recovery-code verification accepted unlimited wrong attempts — "
            "no rate limit on the 2FA recovery path."
        )
