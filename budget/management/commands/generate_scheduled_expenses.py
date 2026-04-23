import calendar
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

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


def occurrences_in_month(scheduled: ScheduledExpense, year: int, month: int) -> list[date]:
    base = scheduled.repeat_base_date
    factor = scheduled.repeat_every_factor
    unit = scheduled.repeat_every_unit

    if not base or not factor or not unit:
        return []

    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])

    if base > month_end:
        return []

    current = base
    while current < month_start:
        nxt = _add_period(current, factor, unit)
        if nxt == current:
            break
        current = nxt
        if current > month_end:
            return []

    results = []
    while current <= month_end:
        results.append(current)
        current = _add_period(current, factor, unit)

    return results


class Command(BaseCommand):
    help = "Generate expenses for a calendar month from all scheduled expenses."

    def add_arguments(self, parser):
        today = timezone.localdate()
        parser.add_argument("--year",  type=int, default=today.year,  help="Target year  (default: current)")
        parser.add_argument("--month", type=int, default=today.month, help="Target month (default: current)")

    def handle(self, *args, **options):
        year  = options["year"]
        month = options["month"]
        self.stdout.write(f"Generating expenses for {year}-{month:02d}…")

        created = skipped = 0

        for scheduled in ScheduledExpense.objects.select_related("owning_feuser", "category").prefetch_related("tags"):
            for occurrence in occurrences_in_month(scheduled, year, month):
                already_exists = Expense.objects.filter(
                    source_scheduled=scheduled,
                    date_due=occurrence,
                ).exists()

                if already_exists:
                    skipped += 1
                    continue

                create_expense(
                    owning_feuser=scheduled.owning_feuser,
                    title=scheduled.title,
                    type=scheduled.type,
                    value=scheduled.value,
                    payee=scheduled.payee,
                    note=scheduled.note,
                    category=scheduled.category,
                    tags=list(scheduled.tags.all()),
                    date_due=occurrence,
                    settled=scheduled.default_settled,
                    source_scheduled=scheduled,
                )
                created += 1
                self.stdout.write(f"  + [{scheduled.owning_feuser.email}] {scheduled.title} on {occurrence}")

        self.stdout.write(self.style.SUCCESS(
            f"Done — {created} created, {skipped} already existed."
        ))
