import getpass
import sys

from django.core.management.base import BaseCommand, CommandError

from feusers.models import FeUser


class Command(BaseCommand):
    help = "Create a new user account."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address for the new user.")
        parser.add_argument("-p", "--password", default=None, help="Password (prompted if omitted).")
        parser.add_argument("--first-name", default=None, help="First name (prompted if omitted in interactive mode).")
        parser.add_argument("--last-name", default=None, help="Last name (prompted if omitted in interactive mode).")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]
        first_name = options["first_name"] or ""
        last_name = options["last_name"] or ""

        if FeUser.objects.filter(email=email).exists():
            raise CommandError(f"A user with email '{email}' already exists.")

        if password is None:
            password = getpass.getpass(f"Password for {email}: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords do not match.")

        if not password:
            raise CommandError("Password must not be empty.")

        interactive = sys.stdin.isatty()
        if not first_name and interactive:
            first_name = input("First name: ").strip()
        if not last_name and interactive:
            last_name = input("Last name: ").strip()

        user = FeUser(email=email, first_name=first_name, last_name=last_name,
                      is_active=True, is_confirmed=True)
        user.set_password(password)
        user.save()

        from budget.fixtures import create_defaults
        create_defaults(user)

        self.stdout.write(self.style.SUCCESS(f"User '{email}' created successfully."))
