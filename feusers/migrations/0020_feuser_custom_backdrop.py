from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0019_feuser_profile_picture"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="custom_backdrop",
            field=models.BooleanField(default=False),
        ),
    ]
