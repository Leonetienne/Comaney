from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feusers', '0030_feuser_app_v_created_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='feuser',
            name='disable_ai_ui',
            field=models.BooleanField(default=False),
        ),
    ]
