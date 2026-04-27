import hashlib

from django.db import migrations

FALLBACK_CODE = "0000000000"
FALLBACK_HASH = hashlib.sha256(FALLBACK_CODE.encode()).hexdigest()


def set_fallback_recovery_hash(apps, schema_editor):
    FeUser = apps.get_model("feusers", "FeUser")
    FeUser.objects.filter(totp_enabled=True, totp_recovery_hash="").update(
        totp_recovery_hash=FALLBACK_HASH
    )


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0012_feuser_totp_recovery_hash"),
    ]

    operations = [
        migrations.RunPython(set_fallback_recovery_hash, migrations.RunPython.noop),
    ]
