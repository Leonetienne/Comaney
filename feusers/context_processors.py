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
    from budget.ai_trial import trial_is_disabled
    trial_ok = bool(settings.AI_TRIAL_API_KEY and settings.AI_TRIAL_USAGE_LIMIT and not trial_is_disabled())
    ctx["ai_smart_create_available"] = bool(
        (feuser and feuser.anthropic_api_key) or trial_ok
    )
    return ctx
