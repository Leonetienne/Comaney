from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0007_feuser_month_offset"),
    ]

    operations = [
        migrations.RemoveField(model_name="feuser", name="month_offset"),
        migrations.AddField(
            model_name="feuser",
            name="month_start_day",
            field=models.SmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="feuser",
            name="month_start_prev",
            field=models.BooleanField(default=False),
        ),
    ]
