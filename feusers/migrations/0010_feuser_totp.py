from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0009_feuser_ai_trial_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="totp_secret",
            field=models.CharField(max_length=64, blank=True),
        ),
        migrations.AddField(
            model_name="feuser",
            name="totp_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
