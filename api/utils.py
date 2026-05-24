import json
from functools import wraps

from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.views.decorators.csrf import csrf_exempt

from budget.date_utils import current_financial_month
from .auth import get_api_user


def _err(msg, status=400):
    return JsonResponse({"error": msg}, status=status)


def _ok(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def _require_auth(fn):
    """Authenticate the request and enforce CSRF for session-based callers.

    Bearer-token clients have no ambient cookies, so CSRF is unnecessary.
    Cookie-authenticated requests (browser same-origin) must supply a valid
    CSRF token for any unsafe method (POST/PATCH/DELETE/PUT).
    """
    @csrf_exempt
    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        user = get_api_user(request)
        if not user:
            return _err("Unauthorized — provide a valid Bearer token.", 401)
        if not request.headers.get("Authorization", "").startswith("Bearer "):
            reason = CsrfViewMiddleware(lambda r: None).process_view(request, fn, args, kwargs)
            if reason is not None:
                return _err("CSRF verification failed.", 403)
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
