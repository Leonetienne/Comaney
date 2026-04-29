from django.core.management.base import BaseCommand

from budget.notifications import process_due_notifications


class Command(BaseCommand):
    help = "Send due-date email notifications for expenses approaching their due date."

    def handle(self, *args, **options):
        self.stdout.write("Sending expense notifications…")
        sent, skipped = process_due_notifications()
        self.stdout.write(self.style.SUCCESS(
            f"Done — {sent} notification(s) sent, {skipped} already up-to-date."
        ))
