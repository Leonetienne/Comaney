"""
Expense notification helpers.

Notification classes (in order of precedence):
  ""        – no notification sent yet / not due soon
  "soon"    – due in 2–4 days
  "tomorrow"– due today or tomorrow
  "late"    – past due date
  "settled" – expense has been paid
"""
from datetime import date
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

CLASS_ORDER = {"": 0, "soon": 1, "tomorrow": 2, "late": 3, "settled": 4}


def compute_initial_class(expense) -> str:
    """
    Return the last_notification_class_sent value that should be set immediately
    after creating or editing an expense, so the cron doesn't spam stale events.
    """
    if expense.settled:
        return "settled"
    if not expense.date_due:
        return ""
    days = (expense.date_due - date.today()).days
    if days < 0:
        return "late"
    if days <= 1:
        return "tomorrow"
    if days < 5:
        return "soon"
    return ""


def set_initial_notification_class(expense) -> None:
    from .models import Expense
    cls = compute_initial_class(expense)
    Expense.objects.filter(pk=expense.pk).update(last_notification_class_sent=cls)
    expense.last_notification_class_sent = cls


def _target_class(expense) -> str:
    """What class the cron should send for an unsettled expense right now."""
    if not expense.date_due:
        return ""
    days = (expense.date_due - date.today()).days
    if days < 0:
        return "late"
    if days <= 1:
        return "tomorrow"
    if days < 5:
        return "soon"
    return ""


def _build_email_context(expense, notification_class: str) -> dict:
    site_url = settings.SITE_URL
    ctx = {
        "expense": expense,
        "feuser": expense.owning_feuser,
        "site_url": site_url,
        "settle_url": f"{site_url}/budget/expenses/{expense.uid}/settle-via-email/",
        "mute_url": f"{site_url}/budget/expenses/{expense.uid}/mute-notifications/",
        "mute_all_url": f"{site_url}/budget/notifications/mute-all/",
    }
    if notification_class == "soon" and expense.date_due:
        ctx["days_until_due"] = (expense.date_due - date.today()).days
    return ctx


def _build_plain_text(expense, notification_class: str, ctx: dict) -> str:
    feuser = expense.owning_feuser
    name = feuser.first_name or feuser.email
    currency = feuser.currency
    if notification_class == "soon":
        days = ctx.get("days_until_due", "")
        intro = f'Your payment "{expense.title}" is due in {days} days ({expense.value} {currency}, on {expense.date_due}).'
    elif notification_class == "tomorrow":
        intro = f'Your payment "{expense.title}" is due tomorrow ({expense.value} {currency}, on {expense.date_due}).'
    elif notification_class == "late":
        intro = f'Your payment "{expense.title}" was due on {expense.date_due} ({expense.value} {currency}) and is still unpaid.'
    else:
        intro = f'Your payment "{expense.title}" ({expense.value} {currency}) has been marked as paid.'

    lines = [f"Hi {name},", "", intro, ""]
    if notification_class != "settled":
        lines += [
            "Mark as paid:",
            ctx["settle_url"],
            "",
        ]
    lines += [
        "Disable notifications for this expense:",
        ctx["mute_url"],
        "",
        "Disable all email notifications:",
        ctx["mute_all_url"],
    ]
    return "\n".join(lines)


def _subject(expense, notification_class: str, ctx: dict) -> str:
    title = expense.title
    if notification_class == "soon":
        days = ctx.get("days_until_due", "")
        return f"Payment due in {days} days: {title}"
    if notification_class == "tomorrow":
        return f"Payment due tomorrow: {title}"
    if notification_class == "late":
        return f"Payment overdue – still unpaid: {title}"
    return f"Payment marked as paid: {title}"


def send_expense_notification(expense, notification_class: str) -> bool:
    """Send an email for the given notification class. Returns True on success."""
    if notification_class not in CLASS_ORDER or not notification_class:
        return False
    feuser = expense.owning_feuser
    ctx = _build_email_context(expense, notification_class)
    subject = _subject(expense, notification_class, ctx)
    plain = _build_plain_text(expense, notification_class, ctx)
    html = render_to_string(f"emails/expense_notification_{notification_class}.html", ctx)
    try:
        send_mail(
            subject=subject,
            message=plain,
            html_message=html,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[feuser.email],
        )
        return True
    except (SMTPException, OSError):
        return False


def send_settled_notification(expense) -> bool:
    """
    Send a "settled" notification for a single expense that just became settled.
    Updates last_notification_class_sent. No-op if already sent or notifications disabled.
    """
    from .models import Expense
    feuser = expense.owning_feuser
    if not feuser.email_notifications or not expense.notify:
        return False
    if expense.last_notification_class_sent == "settled":
        return False
    if send_expense_notification(expense, "settled"):
        Expense.objects.filter(pk=expense.pk).update(last_notification_class_sent="settled")
        expense.last_notification_class_sent = "settled"
        return True
    return False


def process_due_notifications() -> tuple[int, int]:
    """
    Scan all active unsettled expenses and send any pending due-date notifications.
    Returns (sent, skipped).
    """
    from .models import Expense
    sent = skipped = 0
    qs = (
        Expense.objects
        .filter(settled=False, notify=True, deactivated=False, date_due__isnull=False)
        .select_related("owning_feuser")
    )
    for expense in qs:
        feuser = expense.owning_feuser
        if not feuser.email_notifications:
            continue
        target = _target_class(expense)
        if not target:
            continue
        last = expense.last_notification_class_sent or ""
        if CLASS_ORDER.get(last, 0) >= CLASS_ORDER.get(target, 0):
            skipped += 1
            continue
        if send_expense_notification(expense, target):
            Expense.objects.filter(pk=expense.pk).update(last_notification_class_sent=target)
            expense.last_notification_class_sent = target
            sent += 1
    return sent, skipped
