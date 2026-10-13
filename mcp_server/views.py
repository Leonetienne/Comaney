"""Agent key management on the profile page."""
from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from api.registry import CONCERNS
from budget.decorators import feuser_required

from . import permissions
from .models import LABEL_MAX_LENGTH, AgentKey

_FLASH_KEY = "_flash_agent_key"


def _back():
    return redirect(reverse("profile") + "#section-agent-keys")


def profile_context(request, feuser) -> dict:
    """Template context for the profile's agent key card; the fresh secret shows exactly once."""
    keys = list(AgentKey.objects.filter(feuser=feuser))
    return {
        "agent_keys": [
            {
                "key": key,
                "restricted": key.is_restricted(),
                "rows": [
                    {"concern": c, "label": label, **key.effective_permissions()[c]}
                    for c, label in CONCERNS.items()
                ],
            }
            for key in keys
        ],
        "agent_key_flash": request.session.pop(_FLASH_KEY, None),
        "mcp_url": f"{getattr(settings, 'SITE_URL', '').rstrip('/')}/mcp",
        "agent_key_label_max": LABEL_MAX_LENGTH,
    }


@feuser_required
@require_POST
def agent_key_create(request):
    feuser = request.feuser
    if feuser.is_demo:
        return _back()
    label = request.POST.get("label", "").strip()[:LABEL_MAX_LENGTH] or "Agent"
    key, raw = AgentKey.create(feuser, label)
    request.session[_FLASH_KEY] = {"id": key.pk, "secret": raw}
    return _back()


@feuser_required
@require_POST
def agent_key_permissions(request, uid):
    key = get_object_or_404(AgentKey, uid=uid, feuser=request.feuser)
    key.permissions = permissions.from_form(request.POST, CONCERNS)
    key.save(update_fields=["permissions"])
    messages.success(request, f"Permissions of \"{key.label}\" saved.")
    return _back()


@feuser_required
@require_POST
def agent_key_revoke(request, uid):
    key = get_object_or_404(AgentKey, uid=uid, feuser=request.feuser)
    label = key.label
    key.delete()
    messages.success(request, f"Agent key \"{label}\" revoked.")
    return _back()
