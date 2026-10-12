from django.conf import settings
from django.contrib import admin
from django.shortcuts import redirect
from django.template.response import TemplateResponse

from ai_providers import get_provider

from .ai_availability import shared_limit
from .ai_trial import disable_trial, enable_trial, trial_disabled_reason, trial_is_disabled


def ai_trial_admin_view(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "enable":
            enable_trial()
        elif action == "disable":
            disable_trial("Manually disabled by admin.")
        return redirect("admin_ai_trial")

    disabled = trial_is_disabled()
    provider = get_provider()
    context = {
        **admin.site.each_context(request),
        "title": "Shared AI access",
        "disabled": disabled,
        "reason": trial_disabled_reason() if disabled else "",
        "shared_available": bool(provider and provider.has_shared_access()),
        "limit": shared_limit(settings.AI_TRIAL_USAGE_LIMIT, None),
        "provider_name": provider.get_display_name() if provider else "",
        "billing_url": provider.get_billing_url() if provider else "",
    }
    return TemplateResponse(request, "admin/ai_trial.html", context)
