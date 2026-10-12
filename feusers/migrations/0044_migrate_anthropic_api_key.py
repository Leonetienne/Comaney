"""Move every non-empty anthropic_api_key into ai_user_config as the claude
provider's api_key. Written regardless of the active provider, so the keys
survive until an admin has set AI_PROVIDER (see purge_inactive_ai_config)."""
from django.db import migrations


def forwards(apps, schema_editor):
    FeUser = apps.get_model("feusers", "FeUser")
    for user in FeUser.objects.exclude(anthropic_api_key="").only("pk", "anthropic_api_key", "ai_user_config"):
        config = dict(user.ai_user_config or {})
        config["claude"] = {**config.get("claude", {}), "api_key": user.anthropic_api_key}
        user.ai_user_config = config
        user.save(update_fields=["ai_user_config"])


def backwards(apps, schema_editor):
    FeUser = apps.get_model("feusers", "FeUser")
    for user in FeUser.objects.only("pk", "anthropic_api_key", "ai_user_config"):
        key = ((user.ai_user_config or {}).get("claude") or {}).get("api_key", "")
        if key:
            user.anthropic_api_key = key
            user.save(update_fields=["anthropic_api_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0043_feuser_ai_user_config"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
