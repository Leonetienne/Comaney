"""
Expense notification helpers.

Notification classes (in order of precedence):
  ""        – no notification sent yet / not due soon
  "soon"    – due in 2–4 days
  "tomorrow"– due tomorrow (1 day)
  "today"   – due today
  "late"    – past due date
  "settled" – expense has been paid
"""
from datetime import date

from django.conf import settings

CLASS_ORDER = {"": 0, "soon": 1, "tomorrow": 2, "today": 3, "late": 4, "settled": 5}


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
    if days == 0:
        return "today"
    if days == 1:
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
    if days == 0:
        return "today"
    if days == 1:
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
    elif notification_class == "today":
        intro = f'Your payment "{expense.title}" is due today ({expense.value} {currency}).'
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
    if notification_class == "today":
        return f"Payment due today: {title}"
    if notification_class == "late":
        return f"Payment overdue - still unpaid: {title}"
    return f"Payment marked as paid: {title}"


def _in_app_message(expense, notification_class: str, ctx: dict) -> str:
    currency = expense.owning_feuser.currency
    if notification_class == "soon":
        days = ctx.get("days_until_due", "")
        return f'Your payment "{expense.title}" is due in {days} days ({expense.value} {currency}).'
    if notification_class == "tomorrow":
        return f'Your payment "{expense.title}" is due tomorrow ({expense.value} {currency}).'
    if notification_class == "today":
        return f'Your payment "{expense.title}" is due today ({expense.value} {currency}).'
    if notification_class == "late":
        return f'Your payment "{expense.title}" is overdue ({expense.value} {currency}).'
    return f'Your payment "{expense.title}" ({expense.value} {currency}) has been marked as paid.'


def send_expense_notification(expense, notification_class: str) -> bool:
    """
    Create a DB notification and send an email for the given class.
    Returns True on success (email sent or emailing disabled but record created).
    """
    if notification_class not in CLASS_ORDER or not notification_class:
        return False
    feuser = expense.owning_feuser
    if feuser.is_demo:
        return False

    from feusers.notifications_service import emit_notification

    notif_type = "expense_settled" if notification_class == "settled" else "expense_reminders"
    ctx = _build_email_context(expense, notification_class)
    subject = _subject(expense, notification_class, ctx)
    message = _in_app_message(expense, notification_class, ctx)
    plain = _build_plain_text(expense, notification_class, ctx)

    result = emit_notification(
        feuser,
        type=notif_type,
        subject=subject,
        message=message,
        related_expense=expense,
        email_template=f"emails/expense_notification_{notification_class}.html",
        email_ctx={**ctx, "plain_text": plain},
    )
    return result is not None


def send_settled_notification(expense) -> bool:
    """
    Send a "settled" notification for a single expense that just became settled.
    Updates last_notification_class_sent. No-op if already sent or notifications disabled.
    """
    from .models import Expense
    feuser = expense.owning_feuser
    if not expense.notify:
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
        .filter(
            settled=False,
            notify=True,
            deactivated=False,
            is_dummy=False,
            date_due__isnull=False,
            auto_settle_on_due_date=False,
        )
        .select_related("owning_feuser")
    )
    for expense in qs:
        feuser = expense.owning_feuser
        if not feuser.notify_expense_reminders:
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
