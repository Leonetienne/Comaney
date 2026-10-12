from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('buddies', '0017_buddylink_auto_accept'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='ai_preprompt',
            field=models.TextField(blank=True, default=''),
        ),
    ]
