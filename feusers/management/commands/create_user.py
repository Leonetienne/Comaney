import getpass
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ai_providers import get_provider
from feusers import ai_user_config
from feusers.models import FeUser


class Command(BaseCommand):
    help = "Create a new user account."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address for the new user.")
        parser.add_argument("-p", "--password", default=None, help="Password (prompted if omitted).")
        parser.add_argument("--first-name", default=None, help="First name (prompted if omitted in interactive mode).")
        parser.add_argument("--last-name", default=None, help="Last name (prompted if omitted in interactive mode).")
        parser.add_argument("--demo", action="store_true", default=False, help="Mark the account as a demo user.")
        parser.add_argument("--ai-trial-budget", type=int, default=None, metavar="CENTS", help="Override AI trial budget limit in cents.")
        parser.add_argument(
            "--ai-config", action="append", default=[], metavar="KEY=VALUE",
            help="Set one of the user's own AI settings for the active AI provider (repeatable), e.g. api_key=...",
        )

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

        ai_config = _ai_config_from_args(options["ai_config"])

        interactive = sys.stdin.isatty()
        if not first_name and interactive:
            first_name = input("First name: ").strip()
        if not last_name and interactive:
            last_name = input("Last name: ").strip()

        user = FeUser(
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
            is_confirmed=True,
            is_demo=options["demo"],
            special_ai_trial_budget=options["ai_trial_budget"],
            ai_user_config=ai_config,
            app_v_created_at=settings.APP_VERSION,
        )
        user.set_password(password)
        user.save()

        from budget.fixtures import create_defaults
        create_defaults(user)

        self.stdout.write(self.style.SUCCESS(f"User '{email}' created successfully."))


def _ai_config_from_args(items: list[str]) -> dict:
    """ai_user_config from the --ai-config options, validated like the
    profile form for the active provider."""
    if not items:
        return {}
    try:
        submitted = ai_user_config.parse_config_args(items)
    except ValueError as e:
        raise CommandError(str(e))
    provider = get_provider()
    if provider is None:
        raise CommandError("--ai-config needs an active AI provider (AI_PROVIDER).")
    declared = {f.key for f in provider.get_user_fields()}
    unknown = sorted(set(submitted) - declared)
    if unknown:
        raise CommandError(
            f"Unknown AI setting(s) for {provider.get_name()}: {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(declared)) or 'none'}."
        )
    entry, errors = ai_user_config.clean_submission(provider, submitted, {})
    if errors:
        raise CommandError(" ".join(errors.values()))
    return ai_user_config.with_entry(provider.get_name(), entry)
