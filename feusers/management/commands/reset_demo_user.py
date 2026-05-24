from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from feusers.models import FeUser


class Command(BaseCommand):
    help = "Reset the demo user if they have been inactive for at least one week."

    def handle(self, *args, **options):
        if not settings.ENABLE_DEMO_USERS:
            self.stdout.write("ENABLE_DEMO_USERS is not set — skipping.")
            return

        email = settings.DEMO_USER_EMAIL
        password = settings.DEMO_USER_PASSWORD

        if not email or not password:
            self.stdout.write(self.style.WARNING(
                "DEMO_USER_EMAIL or DEMO_USER_PASSWORD not configured — skipping."
            ))
            return

        demo_users = FeUser.objects.filter(is_demo=True)

        # Check condition on any demo user: last_seen not null and older than one week.
        cutoff = timezone.now() - timedelta(weeks=1)
        seen_recently = demo_users.filter(last_seen__isnull=False, last_seen__gt=cutoff)
        never_seen = demo_users.filter(last_seen__isnull=True)
        triggered = demo_users.filter(last_seen__isnull=False, last_seen__lte=cutoff)

        if not triggered.exists():
            if never_seen.exists() and not seen_recently.exists():
                self.stdout.write("Demo user exists but has never been seen — skipping reset.")
            else:
                self.stdout.write("No demo user due for reset yet — skipping.")
            return

        self.stdout.write("Condition met — resetting all demo users.")
        count, _ = demo_users.delete()
        self.stdout.write(f"Deleted {count} demo user(s).")

        budget = settings.DEMO_USER_AI_BUDGET or None
        user = FeUser(
            email=email,
            first_name="Dean",
            last_name="Demo",
            is_active=True,
            is_confirmed=True,
            is_demo=True,
            special_ai_trial_budget=budget,
        )
        user.set_password(password)
        user.save()

        from budget.fixtures import create_defaults
        create_defaults(user)

        self.stdout.write(self.style.SUCCESS(f"Demo user '{email}' created successfully."))
