from django.core.management.base import BaseCommand

from ai_providers import get_provider
from feusers.ai_user_config import purge_foreign
from feusers.models import FeUser


class Command(BaseCommand):
    help = (
        "Delete every user's saved AI settings of providers other than the active one. "
        "Does nothing while no AI provider is active."
    )

    def handle(self, *args, **options):
        provider = get_provider()
        if provider is None:
            self.stdout.write("No AI provider active; nothing purged.")
            return
        purged = 0
        for user in FeUser.objects.only("pk", "ai_user_config").iterator():
            cleaned = purge_foreign(user.ai_user_config, provider.get_name())
            if cleaned != user.ai_user_config:
                user.ai_user_config = cleaned
                user.save(update_fields=["ai_user_config"])
                purged += 1
        self.stdout.write(f"Purged AI settings of inactive providers from {purged} user(s).")
