from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0017_feuser_last_login_last_seen"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="has_seen_achim_intro",
            field=models.BooleanField(default=False),
        ),
    ]
