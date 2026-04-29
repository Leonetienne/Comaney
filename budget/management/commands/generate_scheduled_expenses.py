import calendar
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


class Command(BaseCommand):
    help = "Generate expenses from scheduled expenses for each user's current financial year."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=None, help="Override financial year (applies to all users)")

    def handle(self, *args, **options):
        override_year = options["year"]

        self.stdout.write("Generating scheduled expenses…")
        created = skipped = 0

        for scheduled in ScheduledExpense.objects.select_related("owning_feuser", "category").prefetch_related("tags"):
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

                create_expense(
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
                    source_scheduled=scheduled,
                )
                created += 1
                self.stdout.write(f"  + [{feuser.email}] {scheduled.title} on {occurrence}")

        self.stdout.write(self.style.SUCCESS(
            f"Done — {created} created, {skipped} already existed."
        ))
