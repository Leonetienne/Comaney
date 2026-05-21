from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0022_feuser_backdrop_css"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="notify_expense_reminders",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="feuser",
            name="notify_expense_settled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="feuser",
            name="notify_expense_participation",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="feuser",
            name="notify_expense_approvals",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="feuser",
            name="notify_settlements",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="feuser",
            name="notify_group_activity",
            field=models.BooleanField(default=True),
        ),
    ]
