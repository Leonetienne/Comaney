from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buddies", "0004_buddy_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="dummyuser",
            name="is_archive",
            field=models.BooleanField(default=False),
        ),
    ]
