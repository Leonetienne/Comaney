from django.core.management.base import BaseCommand

from budget.allowance_transition import run_transition_for_user
from feusers.models import FeUser


class Command(BaseCommand):
    help = "Apply unspent-allowance actions for users whose financial month has rolled over."

    def handle(self, *args, **options):
        self.stdout.write("Applying allowance transitions…")
        applied = skipped = 0

        for feuser in FeUser.objects.filter(is_active=True):
            result = run_transition_for_user(feuser)
            if result:
                applied += 1
                self.stdout.write(f"  [{feuser.email}] {result}")
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done — {applied} applied, {skipped} skipped."
        ))
