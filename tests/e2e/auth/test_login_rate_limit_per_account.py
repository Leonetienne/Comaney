"""
Regression test for TICKET-04 — brute-force rate limiting is per-process, in-memory
and IP-only (no per-account dimension).

The login limiter keys only on REMOTE_ADDR and is cleared on any successful login
from that IP. That has two effects the ticket flags; this test targets the
concrete, observable one: **there is no per-account throttle**. An unrelated
successful login from the same IP resets the shared IP bucket, so a stream of
failed attempts against one account never trips a lockout as long as some other
account keeps logging in from the same address.

Construction: hammer the victim account with wrong passwords, and after every few
failures log a *different* account in successfully (which clears the shared IP
bucket). With only an IP bucket, the victim is never throttled. With a per-account
throttle (the fix), the victim's own bucket accumulates and eventually locks out.

EXPECTED TO FAIL until per-account throttling is added: today no lockout appears.

Run with (live stack at :8080 required):
    pytest tests/e2e/auth/test_login_rate_limit_per_account.py -sxv | tee logfile.log
"""
import pytest

from helpers import http_session, form_login, create_confirmed_user, cleanup_user, PASSWORD

THROTTLE_MSG = "Too many failed attempts"


@pytest.fixture(scope="module")
def victim():
    u = create_confirmed_user()
    yield u
    cleanup_user(u["email"])


@pytest.fixture(scope="module")
def clearer():
    """A second, unrelated account used to keep resetting the shared IP bucket."""
    u = create_confirmed_user()
    yield u
    cleanup_user(u["email"])


def _fail_login(email: str):
    """One wrong-password login attempt. Returns the response."""
    return form_login(http_session(), email, "definitely-wrong-password")


def _success_login(email: str) -> bool:
    resp = form_login(http_session(), email, PASSWORD)
    return resp.status_code in (301, 302)


class TestPerAccountLoginThrottle:

    def test_victim_locked_out_despite_ip_bucket_resets(self, victim, clearer):
        # Start from a clean per-IP bucket (a successful login clears it), so
        # prior activity from this host can't pre-trip the limiter.
        assert _success_login(clearer["email"])

        throttled = False
        # Interleave a clearer success after every 4 victim failures so the
        # per-IP bucket never reaches its threshold on its own.
        for i in range(1, 21):
            resp = _fail_login(victim["email"])
            if THROTTLE_MSG in resp.text:
                throttled = True
                break
            if i % 4 == 0:
                assert _success_login(clearer["email"]), \
                    "clearer login should succeed (resets the IP bucket)"

        assert throttled, (
            "Victim account was never throttled despite many failed logins — "
            "there is no per-account brute-force limit (only a per-IP one that "
            "unrelated successful logins keep resetting)."
        )
