from django.core.management.base import BaseCommand, CommandError

from feusers.models import FeUser


class Command(BaseCommand):
    help = "Disable two-factor authentication for a user."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address of the user.")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()

        try:
            user = FeUser.objects.get(email=email)
        except FeUser.DoesNotExist:
            raise CommandError(f"No user found with email '{email}'.")

        if not user.totp_enabled:
            self.stdout.write(f"2FA is not enabled for '{email}'. Nothing to do.")
            return

        user.totp_enabled = False
        user.totp_secret = ""
        user.totp_recovery_hash = ""
        user.save()

        self.stdout.write(self.style.SUCCESS(f"2FA removed for '{email}'."))
