from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0011_feuser_api_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="totp_recovery_hash",
            field=models.CharField(blank=True, max_length=128),
        ),
    ]
