from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('buddies', '0016_project_permission_laxity'),
    ]

    operations = [
        migrations.AddField(
            model_name='buddylink',
            name='user_a_auto_accepts_from_b',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='buddylink',
            name='user_b_auto_accepts_from_a',
            field=models.BooleanField(default=False),
        ),
    ]
