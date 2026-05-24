import json

from django.http import JsonResponse, HttpResponseNotAllowed
from django.utils.timezone import localtime

from ..models import Notification
from ..utils import _get_session_feuser


def notifications_list(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return JsonResponse({"error": "not authenticated"}, status=401)

    qs = (
        Notification.objects
        .filter(owning_feuser=feuser)
        .select_related("related_expense__project")
        .order_by("read", "-created_at")[:60]
    )
    items = []
    for n in qs:
        # Fall back to the expense's project if related_project was not stored at emit time
        project_id = n.related_project_id
        if project_id is None and n.related_expense_id and n.related_expense and n.related_expense.project_id:
            project_id = n.related_expense.project_id
        items.append({
            "id": n.pk,
            "type": n.type,
            "subject": n.subject,
            "message": n.message,
            "created_at": localtime(n.created_at).isoformat(),
            "read": n.read,
            "related_project_id": project_id,
            "related_expense_id": n.related_expense_id,
            "related_feuser_id": n.related_feuser_id,
        })
    return JsonResponse({"notifications": items})


def notifications_mark_read(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    feuser = _get_session_feuser(request)
    if not feuser:
        return JsonResponse({"error": "not authenticated"}, status=401)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        data = {}

    ids = data.get("ids")
    qs = Notification.objects.filter(owning_feuser=feuser, read=False)
    if ids:
        qs = qs.filter(pk__in=ids)
    qs.update(read=True)
    return JsonResponse({"ok": True})


def notifications_delete_read(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    feuser = _get_session_feuser(request)
    if not feuser:
        return JsonResponse({"error": "not authenticated"}, status=401)
    Notification.objects.filter(owning_feuser=feuser, read=True).delete()
    return JsonResponse({"ok": True})
