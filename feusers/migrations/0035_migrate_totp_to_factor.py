from django.db import migrations


def migrate_totp_to_factor(apps, schema_editor):
    FeUser = apps.get_model('feusers', 'FeUser')
    TOTPFactor = apps.get_model('feusers', 'TOTPFactor')
    for user in FeUser.objects.filter(totp_enabled=True).exclude(totp_secret=''):
        TOTPFactor.objects.create(
            feuser=user,
            secret=user.totp_secret,
            is_primary=True,
            label='Authenticator App',
        )


def revert_totp_to_factor(apps, schema_editor):
    FeUser = apps.get_model('feusers', 'FeUser')
    TOTPFactor = apps.get_model('feusers', 'TOTPFactor')
    for factor in TOTPFactor.objects.all():
        FeUser.objects.filter(pk=factor.feuser_id).update(
            totp_enabled=True, totp_secret=factor.secret,
        )
    TOTPFactor.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('feusers', '0034_second_factor_models'),
    ]

    operations = [
        migrations.RunPython(migrate_totp_to_factor, revert_totp_to_factor),
    ]
