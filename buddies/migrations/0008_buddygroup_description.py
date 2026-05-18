from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buddies", "0007_buddygroup_group_picture"),
    ]

    operations = [
        migrations.AddField(
            model_name="buddygroup",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
