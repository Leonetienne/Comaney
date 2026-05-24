from django.core.management import call_command
from django.http import JsonResponse

from budget.models import ScheduledExpense
from ..serializers import _scheduled_json, _apply_scheduled_fields, _set_tags
from ..utils import _err, _ok, _parse_body, _require_auth


@_require_auth
def scheduled(request, feuser):
    if request.method == "GET":
        qs = (
            ScheduledExpense.objects
            .filter(owning_feuser=feuser)
            .select_related("category")
            .prefetch_related("tags")
            .order_by("title")
        )
        return _ok({"scheduled": [_scheduled_json(s) for s in qs]})

    if request.method == "POST":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        s = ScheduledExpense(owning_feuser=feuser, default_auto_settle_on_due_date=False)
        err = _apply_scheduled_fields(s, data, feuser, creating=True)
        if err:
            return _err(err)
        s.save()
        tag_err = _set_tags(s, data, feuser)
        if tag_err:
            return _err(tag_err)
        call_command("generate_scheduled_expenses", user=feuser.email)
        return _ok(_scheduled_json(s), 201)

    return _err("Method not allowed.", 405)


@_require_auth
def scheduled_detail(request, feuser, uid):
    try:
        s = (
            ScheduledExpense.objects
            .select_related("category")
            .prefetch_related("tags")
            .get(uid=uid, owning_feuser=feuser)
        )
    except ScheduledExpense.DoesNotExist:
        return _err("Scheduled expense not found.", 404)

    if request.method == "GET":
        return _ok(_scheduled_json(s))

    if request.method == "PATCH":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        err = _apply_scheduled_fields(s, data, feuser)
        if err:
            return _err(err)
        s.save()
        tag_err = _set_tags(s, data, feuser)
        if tag_err:
            return _err(tag_err)
        call_command("generate_scheduled_expenses", user=feuser.email)
        s.refresh_from_db()
        return _ok(_scheduled_json(s))

    if request.method == "DELETE":
        s.delete()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)
