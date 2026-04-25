from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run all scheduled cron jobs."

    def add_arguments(self, parser):
        parser.add_argument("--year",  type=int, default=None, help="Override financial month year  (applies to all users)")
        parser.add_argument("--month", type=int, default=None, help="Override financial month (applies to all users)")

    def handle(self, *args, **options):
        self.stdout.write("=== run_cron ===")

        kwargs = {}
        if options["year"] and options["month"]:
            kwargs = {"year": options["year"], "month": options["month"]}

        self.stdout.write("\n-- generate_scheduled_expenses --")
        call_command("generate_scheduled_expenses", **kwargs, stdout=self.stdout)

        self.stdout.write("\n-- auto_settle_expenses --")
        call_command("auto_settle_expenses", stdout=self.stdout)

        self.stdout.write(self.style.SUCCESS("\n=== done ==="))

