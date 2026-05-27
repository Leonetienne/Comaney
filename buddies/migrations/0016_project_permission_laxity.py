from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('buddies', '0015_remove_buddyonboardinginvite_dummy'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='permission_laxity',
            field=models.PositiveSmallIntegerField(
                choices=[(0, 'Admin only'), (1, 'Any member')],
                default=0,
            ),
        ),
    ]
