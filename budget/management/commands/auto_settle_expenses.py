from django.core.management.base import BaseCommand
from django.utils import timezone

from budget.models import Expense


class Command(BaseCommand):
    help = "Settle all unsettled expenses whose due date has been reached."

    def handle(self, *args, **options):
        today = timezone.localdate()
        qs = Expense.objects.filter(settled=False, date_due__lte=today)
        count = qs.count()
        qs.update(settled=True)
        self.stdout.write(self.style.SUCCESS(f"Done — {count} expense(s) auto-settled."))
