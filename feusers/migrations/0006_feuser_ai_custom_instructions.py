from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0005_feuser_email_change_token_feuser_pending_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="ai_custom_instructions",
            field=models.TextField(blank=True),
        ),
    ]
