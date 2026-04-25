from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0006_feuser_ai_custom_instructions"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="month_offset",
            field=models.SmallIntegerField(default=0),
        ),
    ]
