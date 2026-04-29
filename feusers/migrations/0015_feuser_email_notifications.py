from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0014_feuser_allowance_transition"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="email_notifications",
            field=models.BooleanField(default=True),
        ),
    ]
