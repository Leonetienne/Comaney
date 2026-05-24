"""
Unified notification emitter.

emit_notification() is the single entry point for all in-app and email
notifications. It checks per-type preferences, creates the DB record, and
optionally sends an email.
"""
from __future__ import annotations

from smtplib import SMTPException

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import NOTIFICATION_TYPE_PREF, Notification


def emit_notification(
    feuser,
    *,
    type: str,
    subject: str,
    message: str,
    related_project=None,
    related_feuser=None,
    related_expense=None,
    email_template: str | None = None,
    email_ctx: dict | None = None,
) -> Notification | None:
    """
    Create a Notification for feuser and optionally send an email.

    The per-type preference (e.g. notify_settlements) gates both the DB record
    and the email. Returns the Notification instance, or None if suppressed.

    email_template: path passed to render_to_string for the HTML email body.
    email_ctx: extra template context; site_url is injected automatically.
               Include a "plain_text" key for the plain-text fallback.
    """
    pref_field = NOTIFICATION_TYPE_PREF.get(type)
    if pref_field and not getattr(feuser, pref_field, True):
        return None

    notification = Notification.objects.create(
        owning_feuser=feuser,
        type=type,
        subject=subject,
        message=message,
        related_project=related_project,
        related_feuser=related_feuser,
        related_expense=related_expense,
    )

    if (
        email_template
        and feuser.email_notifications
        and not feuser.is_demo
        and not getattr(settings, "DISABLE_EMAILING", False)
    ):
        ctx = {**(email_ctx or {}), "site_url": getattr(settings, "SITE_URL", "")}
        plain = ctx.pop("plain_text", "")
        try:
            html = render_to_string(email_template, ctx)
            send_mail(
                subject=subject,
                message=plain,
                html_message=html,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
                recipient_list=[feuser.email],
            )
        except (SMTPException, OSError, Exception):
            pass

    return notification
