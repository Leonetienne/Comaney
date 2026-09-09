from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0040_feuser_enable_early_access"),
    ]

    operations = [
        migrations.AlterField(
            model_name="feuser",
            name="ai_custom_instructions",
            field=models.TextField(blank=True, max_length=4096),
        ),
    ]
