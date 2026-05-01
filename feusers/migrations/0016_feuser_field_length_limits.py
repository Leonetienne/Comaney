from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0015_feuser_email_notifications"),
    ]

    operations = [
        migrations.AlterField(
            model_name="feuser",
            name="first_name",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AlterField(
            model_name="feuser",
            name="last_name",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AlterField(
            model_name="feuser",
            name="ai_custom_instructions",
            field=models.TextField(blank=True, max_length=1024),
        ),
    ]
