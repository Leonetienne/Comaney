"""Manages the billing-disabled flag for the shared Anthropic trial key."""
from __future__ import annotations

import logging
from pathlib import Path
from smtplib import SMTPException

from django.conf import settings

log = logging.getLogger(__name__)


def _flag_path() -> Path:
    default = Path(settings.BASE_DIR) / "ai_trial_disabled.flag"
    return Path(getattr(settings, "AI_TRIAL_DISABLED_FLAG", default))


def trial_is_disabled() -> bool:
    return _flag_path().exists()


def trial_disabled_reason() -> str:
    try:
        return _flag_path().read_text().strip()
    except OSError:
        return ""


def disable_trial(reason: str = "") -> None:
    path = _flag_path()
    try:
        path.write_text(reason or "billing error")
    except OSError:
        log.exception("Could not write AI trial disabled flag to %s", path)


def enable_trial() -> None:
    try:
        _flag_path().unlink(missing_ok=True)
    except OSError:
        log.exception("Could not delete AI trial disabled flag at %s", _flag_path())


def notify_admin_billing(reason: str) -> None:
    if getattr(settings, "DISABLE_EMAILING", False):
        return
    email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "")
    if not email:
        return
    from django.core.mail import send_mail

    site_url = getattr(settings, "SITE_URL", "")
    subject = "[Comaney] Trial API key out of funds — action required"
    body = (
        "The shared Anthropic trial API key has run out of credits.\n\n"
        f"Error detail: {reason}\n\n"
        "Express Creation has been automatically disabled for all trial users.\n\n"
        "Steps to restore:\n"
        "  1. Top up the Anthropic account at https://console.anthropic.com\n"
        f"  2. Re-enable the feature at {site_url}/admin/ai-trial/\n"
    )
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
    except (SMTPException, OSError):
        log.exception("Could not send billing notification to %s", email)
