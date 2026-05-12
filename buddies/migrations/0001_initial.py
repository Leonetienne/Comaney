import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("feusers", "0017_feuser_last_login_last_seen"),
    ]

    operations = [
        migrations.CreateModel(
            name="DummyUser",
            fields=[
                ("uid", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "owning_feuser",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dummy_buddies",
                        to="feusers.feuser",
                    ),
                ),
                ("display_name", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["display_name"]},
        ),
        migrations.CreateModel(
            name="BuddyLink",
            fields=[
                ("uid", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "user_a",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="buddy_links_a",
                        to="feusers.feuser",
                    ),
                ),
                (
                    "user_b",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="buddy_links_b",
                        to="feusers.feuser",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["created_at"],
                "unique_together": {("user_a", "user_b")},
            },
        ),
        migrations.CreateModel(
            name="BuddyInvite",
            fields=[
                ("uid", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "inviter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="buddy_invites_sent",
                        to="feusers.feuser",
                    ),
                ),
                ("invitee_email", models.EmailField()),
                ("token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
            ],
        ),
        migrations.CreateModel(
            name="DummyMergeInvite",
            fields=[
                ("uid", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "inviting_feuser",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="merge_invites_sent",
                        to="feusers.feuser",
                    ),
                ),
                (
                    "dummy",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="merge_invites",
                        to="buddies.dummyuser",
                    ),
                ),
                (
                    "invited_feuser",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="merge_invites_received",
                        to="feusers.feuser",
                    ),
                ),
                ("token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
            ],
        ),
    ]
