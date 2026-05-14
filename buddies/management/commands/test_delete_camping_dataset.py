"""
Deletes the three test users created by test_create_camping_dataset and all
data associated with them (expenses, buddy links, group, dummies, etc.).

Run: python manage.py test_delete_camping_dataset
"""

from django.core.management.base import BaseCommand

from feusers.models import FeUser

TEST_EMAILS = ["anna@test.local", "ben@test.local", "clara@test.local"]


class Command(BaseCommand):
    help = "Delete the camping test dataset users and all their data."

    def handle(self, *args, **options):
        deleted = []
        missing = []

        for email in TEST_EMAILS:
            try:
                user = FeUser.objects.get(email=email)
                user.delete()
                deleted.append(email)
            except FeUser.DoesNotExist:
                missing.append(email)

        for email in deleted:
            self.stdout.write(self.style.SUCCESS(f"Deleted {email}"))
        for email in missing:
            self.stdout.write(self.style.WARNING(f"Not found: {email}"))
