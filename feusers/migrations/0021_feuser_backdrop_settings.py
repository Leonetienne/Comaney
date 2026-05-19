from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0020_feuser_custom_backdrop"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="backdrop_mode",
            field=models.CharField(default="cover", max_length=10),
        ),
        migrations.AddField(
            model_name="feuser",
            name="backdrop_opacity",
            field=models.SmallIntegerField(default=100),
        ),
    ]
