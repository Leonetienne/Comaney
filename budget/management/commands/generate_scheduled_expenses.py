import calendar
import json
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from budget.date_utils import current_financial_month, financial_year_range
from budget.expense_factory import create_expense
from budget.models import Expense, ScheduledExpense


def _add_period(d: date, factor: int, unit: str) -> date:
    if unit == "days":
        return d + timedelta(days=factor)
    if unit == "weeks":
        return d + timedelta(weeks=factor)
    if unit == "months":
        month = d.month + factor
        year = d.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        day = min(d.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    if unit == "years":
        year = d.year + factor
        day = min(d.day, calendar.monthrange(year, d.month)[1])
        return date(year, d.month, day)
    raise ValueError(f"Unknown unit: {unit}")


def occurrences_in_range(scheduled: ScheduledExpense, start: date, end: date) -> list[date]:
    base = scheduled.repeat_base_date
    factor = scheduled.repeat_every_factor
    unit = scheduled.repeat_every_unit

    if not base or not factor or not unit:
        return []

    if base > end:
        return []

    current = base
    while current < start:
        nxt = _add_period(current, factor, unit)
        if nxt == current:
            break
        current = nxt
        if current > end:
            return []

    results = []
    while current <= end:
        results.append(current)
        current = _add_period(current, factor, unit)

    return results


def _apply_solo_spendings(expense, project, creator_feuser):
    """For solo projects with no participants, auto-create a 100% row for the creator."""
    if not project:
        return
    feuser_count = project.members.filter(feuser__isnull=False).count()
    dummy_count = project.members.filter(dummy__isnull=False).count()
    if feuser_count == 1 and dummy_count == 0:
        from buddies.models import BuddySpending
        BuddySpending.objects.filter(expense=expense).delete()
        BuddySpending.objects.create(
            expense=expense,
            participant_feuser=creator_feuser,
            share_percent=100,
        )


def _generate_with_assignment(scheduled: ScheduledExpense, feuser, occurrence: date) -> Expense:
    """Create an expense with buddy assignment applied from the scheduled template."""
    from buddies.services import BuddyExpenseService
    from budget.services import upsert_overlay, create_participant_overlays

    mode = scheduled.assign_buddy_mode
    upfront_type = scheduled.assign_upfront_type
    upfront_feuser = scheduled.assign_upfront_feuser
    upfront_dummy = scheduled.assign_upfront_dummy
    project = scheduled.assign_project if mode == 'group' else None
    spendings = json.loads(scheduled.assign_spendings_json or '[]')

    # Guard: if the referenced project/dummy was NULLed, fall back to plain expense
    if mode == 'group' and project is None:
        return _generate_plain(scheduled, feuser, occurrence)
    if mode == 'single' and upfront_type == 'dummy' and upfront_dummy is None:
        return _generate_plain(scheduled, feuser, occurrence)
    if mode == 'single' and upfront_type == 'feuser' and upfront_feuser is None:
        return _generate_plain(scheduled, feuser, occurrence)

    if upfront_type == 'feuser' and upfront_feuser:
        # Expense is owned by the other feuser, with feuser as initiator
        expense = create_expense(
            owning_feuser=upfront_feuser,
            title=scheduled.title,
            type=scheduled.type,
            value=scheduled.value,
            payee=scheduled.payee,
            note=scheduled.note,
            category=scheduled.category,
            tags=list(scheduled.tags.all()),
            date_due=occurrence,
            settled=False,
            auto_settle_on_due_date=scheduled.default_auto_settle_on_due_date,
            notify=scheduled.notify,
            source_scheduled=scheduled,
            buddy_approved=False,
            project=project,
        )
        upsert_overlay(expense, feuser, scheduled.category, list(scheduled.tags.all()))
        BuddyExpenseService.reconcile_categories_tags(expense, upfront_feuser)
        expense.save(update_fields=["category"])
        if not spendings and project:
            _apply_solo_spendings(expense, project, feuser)
        BuddyExpenseService.set_buddy_spendings(expense, spendings)
        create_participant_overlays(expense)
        if project:
            project.update_lastmod()
    else:
        is_dummy = upfront_type == 'dummy'
        expense = create_expense(
            owning_feuser=feuser,
            title=scheduled.title,
            type=scheduled.type,
            value=scheduled.value,
            payee=scheduled.payee,
            note=scheduled.note,
            category=scheduled.category,
            tags=list(scheduled.tags.all()),
            date_due=occurrence,
            settled=False,
            auto_settle_on_due_date=scheduled.default_auto_settle_on_due_date,
            notify=scheduled.notify,
            source_scheduled=scheduled,
            is_dummy=is_dummy,
            upfront_payee_dummy=upfront_dummy if is_dummy else None,
            project=project,
        )
        if not spendings and project:
            _apply_solo_spendings(expense, project, feuser)
        BuddyExpenseService.set_buddy_spendings(expense, spendings)
        create_participant_overlays(expense)
        if project:
            project.update_lastmod()

    return expense


def _generate_plain(scheduled: ScheduledExpense, feuser, occurrence: date) -> Expense:
    return create_expense(
        owning_feuser=feuser,
        title=scheduled.title,
        type=scheduled.type,
        value=scheduled.value,
        payee=scheduled.payee,
        note=scheduled.note,
        category=scheduled.category,
        tags=list(scheduled.tags.all()),
        date_due=occurrence,
        settled=False,
        auto_settle_on_due_date=scheduled.default_auto_settle_on_due_date,
        notify=scheduled.notify,
        source_scheduled=scheduled,
    )


class Command(BaseCommand):
    help = "Generate expenses from scheduled expenses for each user's current financial year."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=None, help="Override financial year (applies to all users)")
        parser.add_argument("--user", type=str, default=None, help="Limit to a single user by email")

    def handle(self, *args, **options):
        override_year = options["year"]
        user_email = options.get("user")

        self.stdout.write("Generating scheduled expenses…")
        created = skipped = 0

        qs = (
            ScheduledExpense.objects
            .select_related(
                "owning_feuser", "category",
                "assign_upfront_feuser", "assign_upfront_dummy", "assign_project",
            )
            .prefetch_related("tags")
        )
        if user_email:
            qs = qs.filter(owning_feuser__email=user_email)

        for scheduled in qs:
            if scheduled.deactivated:
                continue

            feuser = scheduled.owning_feuser
            year = override_year or current_financial_month(feuser.month_start_day, feuser.month_start_prev)[0]
            start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)

            occurrences = occurrences_in_range(scheduled, start, end)
            if scheduled.end_on:
                occurrences = [d for d in occurrences if d <= scheduled.end_on]

            if not occurrences:
                continue

            existing_dates = set(
                Expense.objects.filter(
                    source_scheduled=scheduled,
                    date_due__gte=start,
                    date_due__lte=end,
                ).values_list("date_due", flat=True)
            )

            if len(existing_dates) >= len(occurrences):
                skipped += len(occurrences)
                continue

            for occurrence in occurrences:
                if occurrence in existing_dates:
                    skipped += 1
                    continue

                if scheduled.assign_buddy_mode:
                    expense = _generate_with_assignment(scheduled, feuser, occurrence)
                else:
                    expense = _generate_plain(scheduled, feuser, occurrence)

                from budget.notifications import set_initial_notification_class
                set_initial_notification_class(expense)
                created += 1
                self.stdout.write(f"  + [{feuser.email}] {scheduled.title} on {occurrence}")

        self.stdout.write(self.style.SUCCESS(
            f"Done — {created} created, {skipped} already existed."
        ))
