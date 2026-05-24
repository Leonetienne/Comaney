from django.http import JsonResponse
from django.views.decorators.http import require_POST

from ..intros import CURRENT_UPGRADE_INTRO_VERSION
from ..models import FeUser
from django.utils import timezone


def _get_feuser(request):
    feuser_id = request.session.get("feuser_id")
    if not feuser_id:
        return None
    try:
        return FeUser.objects.get(pk=feuser_id, is_active=True)
    except FeUser.DoesNotExist:
        return None


@require_POST
def intro_seen(request):
    feuser = _get_feuser(request)
    if feuser and feuser.intro_seen_at is None:
        feuser.intro_seen_at = timezone.now()
        feuser.save(update_fields=["intro_seen_at"])
    return JsonResponse({"ok": True})


@require_POST
def upgrade_intro_seen(request):
    feuser = _get_feuser(request)
    if feuser:
        feuser.last_upgrade_intro_v_seen = CURRENT_UPGRADE_INTRO_VERSION
        feuser.save(update_fields=["last_upgrade_intro_v_seen"])
    return JsonResponse({"ok": True})
