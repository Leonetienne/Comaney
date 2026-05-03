from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0016_feuser_field_length_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="last_login",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="feuser",
            name="last_seen",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
