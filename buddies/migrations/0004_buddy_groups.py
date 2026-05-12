import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buddies", "0003_buddyonboardinginvite"),
        ("feusers", "0017_feuser_last_login_last_seen"),
    ]

    operations = [
        migrations.CreateModel(
            name="BuddyGroup",
            fields=[
                ("uid", models.BigAutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=128)),
                (
                    "admin_feuser",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="administered_groups",
                        to="feusers.feuser",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AlterField(
            model_name="dummyuser",
            name="owning_feuser",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dummy_buddies",
                to="feusers.feuser",
            ),
        ),
        migrations.AddField(
            model_name="dummyuser",
            name="owning_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dummy_members",
                to="buddies.buddygroup",
            ),
        ),
        migrations.CreateModel(
            name="BuddyGroupMember",
            fields=[
                ("uid", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="members",
                        to="buddies.buddygroup",
                    ),
                ),
                (
                    "feuser",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="group_memberships",
                        to="feusers.feuser",
                    ),
                ),
                (
                    "dummy",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="group_memberships",
                        to="buddies.dummyuser",
                    ),
                ),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["joined_at"]},
        ),
        migrations.CreateModel(
            name="BuddyGroupInvite",
            fields=[
                ("uid", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invites",
                        to="buddies.buddygroup",
                    ),
                ),
                (
                    "inviting_feuser",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="group_invites_sent",
                        to="feusers.feuser",
                    ),
                ),
                ("invitee_email", models.EmailField(db_index=True)),
                ("token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
            ],
        ),
        migrations.AddField(
            model_name="buddyonboardinginvite",
            name="group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="onboarding_invites",
                to="buddies.buddygroup",
            ),
        ),
    ]
