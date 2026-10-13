"""REST API v2: one URL per operation path, dispatched by HTTP method to the registry."""
import json
from collections import defaultdict

from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from .auth import get_api_user
from .operations import REGISTRY, Context, OpError, validate_args

_BODYLESS = ("GET", "DELETE")


def _error(message, status):
    return JsonResponse({"error": message}, status=status)


def _read_args(request):
    if request.method in _BODYLESS:
        return {k: v for k, v in request.GET.items()}
    try:
        body = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise OpError("Invalid JSON body.")
    if not isinstance(body, dict):
        raise OpError("The JSON body must be an object.")
    return body


@csrf_exempt
def dispatch(request, routes, **path_args):
    """
    Authenticate by Bearer API key or browser session (session callers need a CSRF
    token for unsafe methods), then run the operation registered for this method.
    """
    op = routes.get(request.method)
    if op is None:
        response = _error("Method not allowed.", 405)
        response["Allow"] = ", ".join(sorted(routes))
        return response
    feuser = get_api_user(request)
    if not feuser:
        return _error("Unauthorized: provide a valid Bearer token.", 401)
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        if CsrfViewMiddleware(lambda r: None).process_view(request, dispatch, (), {}) is not None:
            return _error("CSRF verification failed.", 403)
    try:
        raw = _read_args(request)
        raw.update(path_args)
        args = validate_args(op, raw, from_query=request.method in _BODYLESS, strict=request.method not in _BODYLESS)
        result = op.handler(Context(feuser=feuser), args)
    except OpError as exc:
        return _error(str(exc), exc.status)
    if op.status == 204:
        return HttpResponse(status=204)
    return JsonResponse(result, status=op.status, safe=False, json_dumps_params={"ensure_ascii": False})


def urlpatterns_from_registry():
    routes = defaultdict(dict)
    for op in REGISTRY.values():
        assert op.method not in routes[op.path], f"{op.method} {op.path} registered twice"
        routes[op.path][op.method] = op
    # literal paths before parameterised ones so "cards/reference/" wins over "cards/<int:id>/"
    ordered = sorted(routes.items(), key=lambda item: ("<" in item[0], item[0]))
    return [path(p, dispatch, {"routes": methods}) for p, methods in ordered]
