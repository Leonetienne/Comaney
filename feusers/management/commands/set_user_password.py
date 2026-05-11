import getpass

from django.core.management.base import BaseCommand, CommandError

from feusers.models import FeUser


class Command(BaseCommand):
    help = "Set the password for an existing user."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address of the user.")
        parser.add_argument("-p", "--password", default=None, help="New password (prompted if omitted).")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]

        try:
            user = FeUser.objects.get(email=email)
        except FeUser.DoesNotExist:
            raise CommandError(f"No user found with email '{email}'.")

        if password is None:
            password = getpass.getpass(f"New password for {email}: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords do not match.")

        if not password:
            raise CommandError("Password must not be empty.")

        user.set_password(password)
        user.save()

        self.stdout.write(self.style.SUCCESS(f"Password for '{email}' updated successfully."))
