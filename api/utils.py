import json
from functools import wraps

from django.http import JsonResponse

from budget.date_utils import current_financial_month
from .auth import get_api_user


def _err(msg, status=400):
    return JsonResponse({"error": msg}, status=status)


def _ok(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def _require_auth(fn):
    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        user = get_api_user(request)
        if not user:
            return _err("Unauthorized — provide a valid Bearer token.", 401)
        return fn(request, user, *args, **kwargs)
    return wrapper


def _parse_body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None


def _parse_month(request, feuser):
    """Return (year, month) from query params, falling back to the user's current financial month."""
    cur_year, cur_month = current_financial_month(feuser.month_start_day, feuser.month_start_prev)
    try:
        year = int(request.GET["year"])
    except (KeyError, ValueError):
        year = cur_year
    try:
        month = int(request.GET["month"])
    except (KeyError, ValueError):
        month = cur_month
    return year, month
