from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from budget.models import Expense
from budget.notifications import send_settled_notification


class Command(BaseCommand):
    help = "Settle all unsettled expenses whose due date has been reached."

    def handle(self, *args, **options):
        today = timezone.localdate()
        qs = (
            Expense.objects
            .filter(settled=False, auto_settle_on_due_date=True, date_due__lte=today, deactivated=False)
            .select_related("owning_feuser")
        )
        count = 0
        for expense in qs:
            expense.settled = True
            expense.save(update_fields=["settled"])
            # Only notify if the due date just crossed the threshold (today or yesterday).
            # Old overdue expenses that sat unsettled for days are backfill — no notification.
            if expense.date_due >= today - timedelta(days=1):
                send_settled_notification(expense)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Done — {count} expense(s) auto-settled."))
