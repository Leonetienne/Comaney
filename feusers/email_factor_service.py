"""Email second-factor: a regular TOTP secret whose code is delivered to the
feuser's own inbox on request instead of read off an authenticator app.

Two things distinguish this from feusers/views/totp.py:

- A plain 30s TOTP step would routinely have already expired by the time an
  email arrives and is read, so this uses a much longer step (CODE_INTERVAL).
  The code itself is never stored anywhere (not the DB, not the cache): pyotp
  recomputes it from the persisted secret + current time on every send and
  every verify, so there is nothing transient to leak or clean up.
- Sending is a distinct, throttled action (an authenticator app costs the
  attacker nothing to poll; an email costs an inbox and, at volume, money and
  deliverability). Throttling is keyed on the feuser's own pk (only ever
  resolved from server-side session state, see views/email_factor.py, never
  from a client-supplied id) plus `purpose` - see request_send() - so setup,
  an in-progress login, and an authenticated user acting on their own
  already-registered factor (factor_test, a removal/recovery-regen confirm
  step) each get their own bucket and can't block one another. A successful
  email-code verification, in any of those latter contexts, clears the
  login-purpose bucket via clear_login_send_throttle() (see
  feusers/views/twofa.py's _verify_email_login, its sole caller): proving you
  can read the current code is proof enough that the login gate's throttle
  no longer needs to hold you back.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

import pyotp

from . import rate_limit

CODE_INTERVAL = 300  # seconds per TOTP step; generous enough for email lag
COOLDOWN_SECONDS = 60  # minimum gap between two sends
HOURLY_MAX_SENDS = 10  # hard cap even if something scripts around the UI cooldown

_COOLDOWN_KIND = "email2fa-cooldown"
_HOURLY_KIND = "email2fa-hourly"

TOO_SOON_MSG = "Please wait a moment before requesting another code."
TOO_MANY_MSG = "Too many code requests. Please try again later."


def generate_secret() -> str:
    return pyotp.random_base32()


def _totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret, interval=CODE_INTERVAL)


def verify_code(secret: str, code: str) -> bool:
    return _totp(secret).verify(code, valid_window=1)


# A different template/copy for setup: there is no "sign-in" happening yet,
# so telling the user they're "finishing signing in" is just wrong. Every
# other purpose (an in-progress login, or an authenticated user confirming
# with an already-registered factor) is close enough to "proving who you
# are" that they share the "login" copy.
_TEMPLATES = {
    "setup": ("Confirm your email for two-factor authentication", "emails/second_factor_email_code_setup.html"),
}
_DEFAULT_TEMPLATE = ("Your Comaney sign-in code", "emails/second_factor_email_code.html")


def _send_mail(feuser_email: str, secret: str, purpose: str) -> bool:
    if settings.DISABLE_EMAILING:
        return False
    code = _totp(secret).now()
    subject, template = _TEMPLATES.get(purpose, _DEFAULT_TEMPLATE)
    html = render_to_string(template, {
        "code": code,
        "site_url": getattr(settings, "SITE_URL", ""),
    })
    plain = (
        f"Use this code to confirm two-factor authentication by email: {code}. It expires in a few minutes."
        if purpose == "setup" else
        f"Your sign-in code is {code}. It expires in a few minutes."
    )
    try:
        send_mail(
            subject=subject,
            message=plain,
            html_message=html,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
            recipient_list=[feuser_email],
        )
        return True
    except Exception:
        return False


def request_send(feuser_pk: int, feuser_email: str, secret: str, *, purpose: str = "login") -> tuple[bool, str | None]:
    """Send a fresh code if throttling allows it.

    Returns (True, None) on success, or (False, error_message) if throttled
    or the send itself failed. Both throttle windows are checked before
    sending so a blocked request never triggers an email. `purpose` is one
    of "setup" (confirming a not-yet-registered factor), "login" (an
    in-progress, not-yet-authenticated login), or "confirm" (an already
    authenticated feuser acting on their own already-registered factor:
    factor_test, or a removal/recovery-regen confirm step) - each is its own
    throttle bucket (see clear_login_send_throttle for why "login" also gets
    cleared on a successful verify), so none of them can block the others.
    """
    identity = f"{feuser_pk}:{purpose}"
    if rate_limit.is_limited(_HOURLY_KIND, identity, window=3600, max_attempts=HOURLY_MAX_SENDS):
        return False, TOO_MANY_MSG
    if rate_limit.is_limited(_COOLDOWN_KIND, identity, window=COOLDOWN_SECONDS, max_attempts=1):
        return False, TOO_SOON_MSG

    if not _send_mail(feuser_email, secret, purpose):
        return False, "We couldn't send the email. Please try again."

    rate_limit.record_failure(_HOURLY_KIND, identity, window=3600)
    rate_limit.record_failure(_COOLDOWN_KIND, identity, window=COOLDOWN_SECONDS)
    return True, None


def clear_login_send_throttle(feuser_pk: int) -> None:
    """Called on every successful email-code verification (see
    feusers/views/twofa.py's _verify_email_login) to reset the "login"
    purpose's send throttle: correctly entering the current code is proof
    the account owner can read their inbox, which is exactly what the
    throttle exists to gate on in the first place, so there's no reason to
    keep them waiting out its cooldown afterward - e.g. logging out and
    immediately signing back in, or logging in right after a successful
    factor_test. Only "login" is cleared; "setup" and "confirm" are
    independent buckets and unaffected.
    """
    identity = f"{feuser_pk}:login"
    rate_limit.clear(_COOLDOWN_KIND, identity)
    rate_limit.clear(_HOURLY_KIND, identity)
