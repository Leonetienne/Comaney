from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buddies", "0006_dummyuser_profile_picture"),
    ]

    operations = [
        migrations.AddField(
            model_name="buddygroup",
            name="group_picture",
            field=models.BooleanField(default=False),
        ),
    ]
