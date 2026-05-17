from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buddies", "0005_dummyuser_is_archive"),
    ]

    operations = [
        migrations.AddField(
            model_name="dummyuser",
            name="profile_picture",
            field=models.BooleanField(default=False),
        ),
    ]
