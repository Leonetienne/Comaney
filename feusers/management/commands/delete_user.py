from django.core.management.base import BaseCommand, CommandError

from feusers.models import FeUser


class Command(BaseCommand):
    help = "Permanently delete a user account and all associated data."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address of the user to delete.")
        parser.add_argument(
            "--yes",
            action="store_true",
            default=False,
            help="Skip the confirmation prompt.",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()

        try:
            user = FeUser.objects.get(email=email)
        except FeUser.DoesNotExist:
            raise CommandError(f"No user found with email '{email}'.")

        if not options["yes"]:
            confirm = input(f"Delete user '{email}' and all associated data? [yes/N] ").strip()
            if confirm.lower() != "yes":
                self.stdout.write("Aborted.")
                return

        user.delete()
        self.stdout.write(self.style.SUCCESS(f"User '{email}' deleted."))
