from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('feusers', '0035_migrate_totp_to_factor'),
    ]

    operations = [
        migrations.RenameField(
            model_name='feuser',
            old_name='totp_recovery_hash',
            new_name='twofa_recovery_hash',
        ),
    ]
