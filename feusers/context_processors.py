from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ai_providers import get_provider

from .help_fab import get_help_fab as _get_help_fab
from .intros import CURRENT_UPGRADE_INTRO_VERSION
from .models import FeUser, Notification


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
    ctx["demo_users_enabled"] = settings.ENABLE_DEMO_USERS
    ctx["demo_user_email"] = settings.DEMO_USER_EMAIL
    ctx["demo_user_password"] = settings.DEMO_USER_PASSWORD
    feuser = ctx["current_feuser"]
    from budget.ai_availability import ai_ui_available, vision_available
    from budget.ai_service import AIService
    provider = get_provider()
    ctx["ai_smart_create_available"] = ai_ui_available(
        AIService.access_for(feuser), bool(feuser and feuser.disable_ai_ui),
    )
    ctx["ai_vision_available"] = vision_available(
        ctx["ai_smart_create_available"], bool(provider and provider.supports_vision()),
    )
    ctx["ai_enabled"] = provider is not None
    ctx["ai_provider_display_name"] = provider.get_display_name() if provider else ""
    ctx["ai_provider_vendor_name"] = provider.get_vendor_name() if provider else ""
    ctx["ai_sends_data_off_server"] = bool(provider and provider.sends_data_off_server())
    ctx["sankey_studio_available"] = bool(feuser and feuser.enable_early_access)
    ctx["email_2fa_available"] = not settings.DISABLE_EMAILING
    ctx["unread_notification_count"] = (
        Notification.objects.filter(owning_feuser=feuser, read=False).count()
        if feuser else 0
    )

    ctx["show_intro_modal"] = bool(feuser and feuser.intro_seen_at is None)

    if feuser and feuser.intro_seen_at is not None:
        intro_is_recent = (timezone.now() - feuser.intro_seen_at) < timedelta(days=30)
        needs_upgrade_intro = (
            feuser.last_upgrade_intro_v_seen is None
            or feuser.last_upgrade_intro_v_seen < CURRENT_UPGRADE_INTRO_VERSION
        )
        created_on_current_version = feuser.app_v_created_at == settings.APP_VERSION
        ctx["show_upgrade_intro_modal"] = (
            needs_upgrade_intro and not intro_is_recent and not created_on_current_version
        )
    else:
        ctx["show_upgrade_intro_modal"] = False

    ctx["help_fab_url"] = _get_help_fab(request.path)

    return ctx
