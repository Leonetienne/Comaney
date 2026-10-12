"""Disabled flag for the shared AI access, and the admin emails about it."""
from __future__ import annotations

import logging
from pathlib import Path
from smtplib import SMTPException

from django.conf import settings

from ai_providers.base import AIProvider, env_var_name

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


def shared_key_setting(provider: AIProvider) -> str:
    """Env var holding the provider's shared API key, or its settings prefix if it has none."""
    if any(f.key == "api_key" for f in provider.get_config_fields()):
        return env_var_name(provider.get_name(), "api_key")
    return env_var_name(provider.get_name(), "") + "*"


def invalid_key_text(provider: AIProvider) -> str:
    return (
        f"{provider.get_display_name()} rejected the shared API key (authentication error).\n\n"
        "Users without their own AI settings get an error from every AI feature.\n\n"
        "Steps to fix:\n"
        f"  1. Set a valid {shared_key_setting(provider)} in your environment\n"
        "  2. Restart the container\n"
    )


def billing_text(provider: AIProvider, reason: str, site_url: str) -> str:
    billing_url = provider.get_billing_url()
    top_up = f"at {billing_url}" if billing_url else "with your AI service"
    return (
        f"The shared {provider.get_display_name()} access has run out of credits.\n\n"
        f"Error detail: {reason}\n\n"
        "Shared AI access has been disabled automatically for all users without their own AI settings.\n\n"
        "Steps to restore:\n"
        f"  1. Top up the account {top_up}\n"
        f"  2. Re-enable shared access at {site_url}/admin/ai-trial/\n"
    )


def notify_admin_invalid_trial_key() -> None:
    if getattr(settings, "DISABLE_EMAILING", False):
        return
    email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "")
    if not email:
        return
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    from ai_providers import get_provider

    provider = get_provider()
    subject = "[Comaney] Shared AI key is invalid: action required"
    html_body = render_to_string("emails/trial_key_invalid.html", {
        "provider_name": provider.get_display_name(),
        "key_setting": shared_key_setting(provider),
    })
    text_body = invalid_key_text(provider)
    try:
        msg = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [email])
        msg.attach_alternative(html_body, "text/html")
        msg.send()
    except (SMTPException, OSError):
        log.exception("Could not send invalid trial key notification to %s", email)


def notify_admin_json_repair_fallback(feature: str, resolved: bool) -> None:
    """
    A JSON-repair fallback (see budget.ai_service.AIService._call_and_repair)
    had to kick in: an AI feature's response didn't parse as JSON at all
    (usually excessive markdown/code-fencing or stray text around it), so a
    second AI call was made to try to recover it. Purely an operational
    signal for the admin -- never includes any user data or response
    content, just which feature hit this and whether the retry fixed it.
    Switched off with AI_NOTIFY_ADMIN_JSON_REPAIR=FALSE.
    """
    if getattr(settings, "DISABLE_EMAILING", False) or not getattr(settings, "AI_NOTIFY_ADMIN_JSON_REPAIR", True):
        return
    email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "")
    if not email:
        return
    from django.core.mail import send_mail

    outcome = (
        "The repair attempt fixed it and the request completed normally."
        if resolved else
        "The repair attempt also failed; the request was shown as failed to the user."
    )
    subject = f"[Comaney] AI JSON extraction needed a repair fallback ({feature})"
    body = (
        f'The AI feature "{feature}" returned a response that could not be parsed as JSON, '
        f"likely due to excessive markdown/code-fencing or stray text around the JSON.\n\n"
        f"A second AI call was made to repair the response. {outcome}\n\n"
        "This is an operational notice only; no user or response data is included.\n"
    )
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
    except (SMTPException, OSError):
        log.exception("Could not send JSON-repair-fallback notification to %s", email)


def notify_admin_billing(reason: str) -> None:
    if getattr(settings, "DISABLE_EMAILING", False):
        return
    email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "")
    if not email:
        return
    from django.core.mail import send_mail

    from ai_providers import get_provider

    subject = "[Comaney] Shared AI access out of funds: action required"
    body = billing_text(get_provider(), reason, getattr(settings, "SITE_URL", ""))
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
    except (SMTPException, OSError):
        log.exception("Could not send billing notification to %s", email)
