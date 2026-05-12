import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0014_default_dashboard_cards"),
        ("buddies", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="is_dummy",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="expense",
            name="buddy_approved",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="expense",
            name="upfront_payee_dummy",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="upfront_expenses",
                to="buddies.dummyuser",
            ),
        ),
    ]
