from django.contrib import admin
from django.shortcuts import redirect
from django.template.response import TemplateResponse

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
    context = {
        **admin.site.each_context(request),
        "title": "Express Creation — Trial API Status",
        "disabled": disabled,
        "reason": trial_disabled_reason() if disabled else "",
    }
    return TemplateResponse(request, "admin/ai_trial.html", context)
