from django.core.management.base import BaseCommand
from django.utils import timezone

from feusers.models import FeUser


class Command(BaseCommand):
    help = "Zero out ai_trial_budget_spent for all users (run monthly)."

    def handle(self, *args, **options):
        now = timezone.now()
        updated = FeUser.objects.filter(ai_trial_budget_spent__gt=0).update(
            ai_trial_budget_spent=0,
            ai_trial_budget_last_reset=now,
        )
        self.stdout.write(self.style.SUCCESS(f"Reset trial budget for {updated} user(s)."))
