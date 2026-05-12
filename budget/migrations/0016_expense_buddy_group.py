import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0015_expense_buddy_fields"),
        ("buddies", "0004_buddy_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="buddy_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="expenses",
                to="buddies.buddygroup",
            ),
        ),
    ]
