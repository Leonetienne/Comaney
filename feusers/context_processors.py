from django.conf import settings

from .models import FeUser


def current_feuser(request):
    feuser_id = request.session.get("feuser_id")
    if not feuser_id:
        ctx = {"current_feuser": None}
    else:
        try:
            ctx = {"current_feuser": FeUser.objects.get(pk=feuser_id, is_active=True)}
        except FeUser.DoesNotExist:
            ctx = {"current_feuser": None}
    ctx["registration_enabled"] = settings.ENABLE_REGISTRATION
    feuser = ctx["current_feuser"]
    ctx["ai_smart_create_available"] = bool(
        (feuser and feuser.anthropic_api_key) or
        (settings.AI_TRIAL_API_KEY and settings.AI_TRIAL_USAGE_LIMIT)
    )
    return ctx
