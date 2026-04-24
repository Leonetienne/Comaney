from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Run all scheduled cron jobs."

    def add_arguments(self, parser):
        today = timezone.localdate()
        parser.add_argument("--year",  type=int, default=today.year,  help="Target year  (default: current)")
        parser.add_argument("--month", type=int, default=today.month, help="Target month (default: current)")

    def handle(self, *args, **options):
        self.stdout.write("=== run_cron ===")

        self.stdout.write("\n-- generate_scheduled_expenses --")
        call_command("generate_scheduled_expenses", year=options["year"], month=options["month"], stdout=self.stdout)

        self.stdout.write("\n-- auto_settle_expenses --")
        call_command("auto_settle_expenses", stdout=self.stdout)

        self.stdout.write(self.style.SUCCESS("\n=== done ==="))
