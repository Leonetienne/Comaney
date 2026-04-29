from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0007_remove_scheduledexpense_default_settled"),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="deactivated",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="scheduledexpense",
            name="deactivated",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="scheduledexpense",
            name="end_on",
            field=models.DateField(null=True, blank=True),
        ),
    ]
