from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0018_feuser_has_seen_achim_intro"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="profile_picture",
            field=models.BooleanField(default=False),
        ),
    ]
