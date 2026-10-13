"""Recurring expense writes shared by the web views, the REST API and the MCP server."""
import json

from django.core.management import call_command

from .date_utils import current_financial_month, financial_year_range
from .models import Expense, ScheduledExpense

SCHEDULE_FIELDS = ("repeat_every_factor", "repeat_every_unit")
WINDOW_FIELDS = ("repeat_base_date", "end_on")


def generate_and_notify(scheduled: ScheduledExpense, feuser) -> None:
    """Materialize due occurrences for feuser, then notify participants of the new expenses."""
    from buddies.services import BuddyEmailService

    existing_ids = set(Expense.objects.filter(source_scheduled=scheduled).values_list("uid", flat=True))
    call_command("generate_scheduled_expenses", user=feuser.email)
    new_expenses = (
        Expense.objects
        .filter(source_scheduled=scheduled)
        .exclude(uid__in=existing_ids)
        .prefetch_related("buddy_spendings__participant_feuser", "buddy_spendings__participant_dummy")
    )
    for expense in new_expenses:
        BuddyEmailService.notify_expense_created(expense, feuser)


def apply_assignment(obj: ScheduledExpense, buddy: dict | None) -> None:
    """Write a parse_assignment() result onto a recurring expense; None clears it."""
    if not buddy:
        obj.assign_buddy_mode = ""
        obj.assign_upfront_type = "me"
        obj.assign_upfront_feuser = None
        obj.assign_upfront_dummy = None
        obj.assign_project = None
        obj.assign_spendings_json = "[]"
    else:
        obj.assign_buddy_mode = buddy["mode"]
        obj.assign_upfront_type = buddy["upfront_type"]
        obj.assign_upfront_feuser = buddy.get("upfront_feuser")
        obj.assign_upfront_dummy = buddy.get("upfront_dummy")
        obj.assign_project = buddy.get("group") if buddy["mode"] == "group" else None
        obj.assign_spendings_json = json.dumps(buddy.get("spendings", []))


def save_new_scheduled(feuser, obj: ScheduledExpense, tags, buddy) -> ScheduledExpense:
    obj.owning_feuser = feuser
    apply_assignment(obj, buddy)
    obj.save()
    obj.tags.set(tags)
    generate_and_notify(obj, feuser)
    return obj


def update_scheduled(feuser, obj: ScheduledExpense, tags, buddy, *, confirm_schedule, confirm_window,
                     keep_assignment=False) -> ScheduledExpense:
    """
    Save an edited recurring expense. Repeat factor/unit change only with
    confirm_schedule (regenerates this financial year), base date/end only with
    confirm_window (prunes and adds occurrences); unconfirmed changes are discarded.
    """
    before = ScheduledExpense.objects.get(pk=obj.pk)
    if not confirm_schedule:
        for field in SCHEDULE_FIELDS:
            setattr(obj, field, getattr(before, field))
    if not confirm_window:
        for field in WINDOW_FIELDS:
            setattr(obj, field, getattr(before, field))
    if not keep_assignment:
        apply_assignment(obj, buddy)
    obj.save()
    obj.tags.set(tags)

    schedule_changed = any(getattr(before, f) != getattr(obj, f) for f in SCHEDULE_FIELDS)
    window_changed = any(getattr(before, f) != getattr(obj, f) for f in WINDOW_FIELDS)
    if confirm_schedule and schedule_changed:
        year = current_financial_month(feuser.month_start_day, feuser.month_start_prev)[0]
        start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
        Expense.objects.filter(
            source_scheduled=obj,
            scheduled_occurrence_date__gte=start,
            scheduled_occurrence_date__lte=end,
        ).delete()
        obj.last_run = None
        obj.save(update_fields=["last_run"])
    elif confirm_window and window_changed:
        obj.last_run = None
        obj.save(update_fields=["last_run"])

    generate_and_notify(obj, feuser)
    return obj


def clone_scheduled(original: ScheduledExpense) -> ScheduledExpense:
    tags = list(original.tags.all())
    original.pk = None
    original.title = f"CLONE - {original.title}"
    original.save()
    original.tags.set(tags)
    return original


def current_year_expenses(feuser, scheduled):
    """Expenses this recurring expense generated in feuser's current financial year."""
    year = current_financial_month(feuser.month_start_day, feuser.month_start_prev)[0]
    start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
    return Expense.objects.filter(
        source_scheduled=scheduled, owning_feuser=feuser, date_due__gte=start, date_due__lte=end,
    )


def apply_to_expenses(feuser, scheduled, expense_ids) -> int:
    """Copy the recurring expense's current fields and assignment onto some of its generated expenses."""
    from buddies.services import BuddyEmailService, BuddyExpenseService, BuddyTrustService

    expenses = list(
        Expense.objects.filter(
            uid__in=expense_ids, source_scheduled=scheduled, owning_feuser=feuser,
        ).select_related("project")
    )
    mode = scheduled.assign_buddy_mode
    upfront_type = scheduled.assign_upfront_type
    spendings = json.loads(scheduled.assign_spendings_json or "[]")
    tags = list(scheduled.tags.all())

    for expense in expenses:
        old_title = expense.title
        old_value = expense.value
        old_participants = {
            bs.participant_feuser_id: (bs.participant_feuser, bs.share_percent)
            for bs in expense.buddy_spendings.select_related("participant_feuser").filter(participant_feuser__isnull=False)
        }

        expense.title = scheduled.title
        expense.payee = scheduled.payee
        expense.note = scheduled.note
        expense.category = scheduled.category
        expense.type = scheduled.type
        expense.value = scheduled.value
        expense.auto_settle_on_due_date = scheduled.default_auto_settle_on_due_date
        expense.notify = scheduled.notify

        if not mode:
            expense.is_dummy = False
            expense.upfront_payee_dummy = None
            expense.project = None
        elif mode == "group":
            expense.is_dummy = False
            expense.upfront_payee_dummy = None
            expense.project = scheduled.assign_project
        elif mode == "single":
            expense.project = None
            if upfront_type == "dummy" and scheduled.assign_upfront_dummy:
                expense.is_dummy = True
                expense.upfront_payee_dummy = scheduled.assign_upfront_dummy
            else:
                expense.is_dummy = False
                expense.upfront_payee_dummy = None

        expense.save()
        expense.tags.set(tags)
        BuddyExpenseService.set_buddy_spendings(expense, spendings)
        BuddyTrustService.record_action(expense, feuser)
        if expense.project:
            expense.project.update_lastmod()
        BuddyEmailService.notify_expense_updated(expense, feuser, old_title, old_value, old_participants)

    return len(expenses)
