from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0023_feuser_notification_classes"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="feuser",
            name="notify_expense_approvals",
        ),
        migrations.AddField(
            model_name="feuser",
            name="notify_expense_assignments",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="feuser",
            name="notify_participant_decisions",
            field=models.BooleanField(default=True),
        ),
    ]
