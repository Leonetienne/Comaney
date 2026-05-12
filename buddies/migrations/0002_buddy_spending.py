import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buddies", "0001_initial"),
        ("budget", "0015_expense_buddy_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="BuddySpending",
            fields=[
                ("uid", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "expense",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="buddy_spendings",
                        to="budget.expense",
                    ),
                ),
                (
                    "participant_feuser",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="buddy_spending_rows",
                        to="feusers.feuser",
                    ),
                ),
                (
                    "participant_dummy",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="buddy_spending_rows",
                        to="buddies.dummyuser",
                    ),
                ),
                (
                    "share_percent",
                    models.DecimalField(decimal_places=3, max_digits=6),
                ),
            ],
            options={"ordering": ["uid"]},
        ),
    ]
