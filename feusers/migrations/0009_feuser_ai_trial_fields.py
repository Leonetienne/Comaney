from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0008_replace_month_offset"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="ai_trial_budget_spent",
            field=models.DecimalField(max_digits=8, decimal_places=4, default=0),
        ),
        migrations.AddField(
            model_name="feuser",
            name="ai_trial_budget_last_reset",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
