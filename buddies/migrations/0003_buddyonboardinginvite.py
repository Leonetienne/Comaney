import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buddies", "0002_buddy_spending"),
        ("feusers", "0017_feuser_last_login_last_seen"),
    ]

    operations = [
        migrations.CreateModel(
            name="BuddyOnboardingInvite",
            fields=[
                ("uid", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "inviting_feuser",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="onboarding_invites_sent",
                        to="feusers.feuser",
                    ),
                ),
                (
                    "dummy",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="onboarding_invites",
                        to="buddies.dummyuser",
                    ),
                ),
                ("invitee_email", models.EmailField(db_index=True)),
                ("token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
            ],
        ),
    ]
