from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from budget.models import Category
from ..utils import _err, _ok, _parse_body, _require_auth


@csrf_exempt
@_require_auth
def categories(request, feuser):
    if request.method == "GET":
        qs = Category.objects.filter(owning_feuser=feuser)
        return _ok({"categories": [{"id": c.uid, "title": c.title} for c in qs]})

    if request.method == "POST":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        title = str(data.get("title", "")).strip()
        if not title:
            return _err("'title' is required.")
        if len(title) > 128:
            return _err("'title' must be 128 characters or fewer.")
        cat = Category.objects.create(owning_feuser=feuser, title=title)
        return _ok({"id": cat.uid, "title": cat.title}, 201)

    return _err("Method not allowed.", 405)


@csrf_exempt
@_require_auth
def category_detail(request, feuser, uid):
    try:
        cat = Category.objects.get(uid=uid, owning_feuser=feuser)
    except Category.DoesNotExist:
        return _err("Category not found.", 404)

    if request.method == "GET":
        return _ok({"id": cat.uid, "title": cat.title})

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
            cat.title = title
            cat.save(update_fields=["title"])
        return _ok({"id": cat.uid, "title": cat.title})

    if request.method == "DELETE":
        cat.delete()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)
