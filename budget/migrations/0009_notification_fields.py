from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0008_deactivated_and_end_on"),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="notify",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="expense",
            name="last_notification_class_sent",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
        migrations.AddField(
            model_name="scheduledexpense",
            name="notify",
            field=models.BooleanField(default=True),
        ),
    ]
