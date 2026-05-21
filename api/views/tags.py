from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from budget.models import Tag
from ..utils import _err, _ok, _parse_body, _require_auth


@csrf_exempt
@_require_auth
def tags(request, feuser):
    if request.method == "GET":
        qs = Tag.objects.filter(owning_feuser=feuser)
        return _ok({"tags": [{"id": t.uid, "title": t.title} for t in qs]})

    if request.method == "POST":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        title = str(data.get("title", "")).strip()
        if not title:
            return _err("'title' is required.")
        if len(title) > 128:
            return _err("'title' must be 128 characters or fewer.")
        tag = Tag.objects.create(owning_feuser=feuser, title=title)
        return _ok({"id": tag.uid, "title": tag.title}, 201)

    return _err("Method not allowed.", 405)


@csrf_exempt
@_require_auth
def tag_detail(request, feuser, uid):
    try:
        tag = Tag.objects.get(uid=uid, owning_feuser=feuser)
    except Tag.DoesNotExist:
        return _err("Tag not found.", 404)

    if request.method == "GET":
        return _ok({"id": tag.uid, "title": tag.title})

    if request.method == "PATCH":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        if "title" in data:
            title = str(data["title"]).strip()
            if not title:
                return _err("'title' must not be empty.")
            if len(title) > 128:
                return _err("'title' must be 128 characters or fewer.")
            tag.title = title
            tag.last_mod = timezone.now()
            tag.save(update_fields=["title", "last_mod"])
        return _ok({"id": tag.uid, "title": tag.title})

    if request.method == "DELETE":
        tag.delete()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)
