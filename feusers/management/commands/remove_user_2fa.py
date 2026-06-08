from django.core.management.base import BaseCommand, CommandError

from feusers.models import FeUser
from feusers.second_factor_registry import get_all_factors


class Command(BaseCommand):
    help = "Remove every second-factor method (TOTP, security keys) for a user."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address of the user.")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()

        try:
            user = FeUser.objects.get(email=email)
        except FeUser.DoesNotExist:
            raise CommandError(f"No user found with email '{email}'.")

        factors = get_all_factors(user)
        if not factors:
            self.stdout.write(f"2FA is not enabled for '{email}'. Nothing to do.")
            return

        for factor in factors:
            factor.delete()
        user.twofa_recovery_hash = ""
        user.save(update_fields=["twofa_recovery_hash"])

        self.stdout.write(self.style.SUCCESS(f"2FA removed for '{email}'."))
