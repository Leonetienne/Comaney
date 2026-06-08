from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('feusers', '0036_rename_totp_recovery_hash'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='feuser',
            name='totp_secret',
        ),
        migrations.RemoveField(
            model_name='feuser',
            name='totp_enabled',
        ),
    ]
