import getpass

from django.core.management.base import BaseCommand, CommandError

from feusers.models import FeUser


class Command(BaseCommand):
    help = "Create a new user account."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address for the new user.")
        parser.add_argument("-p", "--password", default=None, help="Password (prompted if omitted).")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]

        if FeUser.objects.filter(email=email).exists():
            raise CommandError(f"A user with email '{email}' already exists.")

        if password is None:
            password = getpass.getpass(f"Password for {email}: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords do not match.")

        if not password:
            raise CommandError("Password must not be empty.")

        user = FeUser(email=email, is_active=True, is_confirmed=True)
        user.set_password(password)
        user.save()

        from budget.fixtures import create_defaults
        create_defaults(user)

        self.stdout.write(self.style.SUCCESS(f"User '{email}' created successfully."))
