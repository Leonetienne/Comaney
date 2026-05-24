"""
Dashboard API endpoints (session auth, not Bearer).

Endpoints:
    GET/POST   /budget/dashboards/
    PATCH/DEL  /budget/dashboards/<uid>/
    POST       /budget/dashboards/reorder/
"""

import json

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..decorators import feuser_required
from ..models import Dashboard


def _ok(data: dict, status: int = 200) -> JsonResponse:
    return JsonResponse(data, status=status)


def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({'error': msg}, status=status)


def _parse_body(request) -> dict:
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}


def _dash_to_json(dash: Dashboard) -> dict:
    return {
        'id':      dash.pk,
        'title':   dash.title,
        'sorting': dash.sorting,
        'url':     f'/budget/dash/{dash.pk}/',
    }


def _first_dashboard(feuser):
    """Return the user's first dashboard (lowest sorting, then lowest uid)."""
    return (
        Dashboard.objects.filter(owning_feuser=feuser)
        .order_by('sorting', 'uid')
        .first()
    )


@feuser_required
@require_http_methods(['GET', 'POST'])
def dashboards_api(request):
    feuser = request.feuser

    if request.method == 'GET':
        dashes = list(Dashboard.objects.filter(owning_feuser=feuser))
        return _ok({'dashboards': [_dash_to_json(d) for d in dashes]})

    # POST: create a new dashboard
    body = _parse_body(request)
    title = body.get('title', '').strip()
    if not title:
        title = 'Dashboard'
    if len(title) > 128:
        return _err('Title too long (max 128 characters)')

    # Place the new dashboard after all existing ones
    last = (
        Dashboard.objects.filter(owning_feuser=feuser)
        .order_by('-sorting', '-uid')
        .first()
    )
    sorting = (last.sorting + 1) if last else 0

    dash = Dashboard.objects.create(
        owning_feuser=feuser,
        title=title,
        sorting=sorting,
    )
    return _ok({'dashboard': _dash_to_json(dash)}, status=201)


@feuser_required
@require_http_methods(['PATCH', 'DELETE'])
def dashboard_detail_api(request, uid: int):
    feuser = request.feuser
    try:
        dash = Dashboard.objects.get(pk=uid, owning_feuser=feuser)
    except Dashboard.DoesNotExist:
        return _err('Not found', 404)

    if request.method == 'DELETE':
        if Dashboard.objects.filter(owning_feuser=feuser).count() <= 1:
            return _err('Cannot delete the only dashboard', 409)
        dash.delete()
        return _ok({'deleted': True})

    # PATCH: rename
    body = _parse_body(request)
    title = body.get('title', '').strip()
    if not title:
        return _err('title is required')
    if len(title) > 128:
        return _err('Title too long (max 128 characters)')

    dash.title = title
    dash.save(update_fields=['title'])
    return _ok({'dashboard': _dash_to_json(dash)})


@feuser_required
@require_http_methods(['POST'])
def dashboards_reorder_api(request):
    feuser = request.feuser
    body = _parse_body(request)
    order = body.get('order', [])

    if not isinstance(order, list):
        return _err('order must be a list of ids')

    dashes = {d.pk: d for d in Dashboard.objects.filter(owning_feuser=feuser)}
    for idx, dash_id in enumerate(order):
        if dash_id in dashes:
            dashes[dash_id].sorting = idx
            dashes[dash_id].save(update_fields=['sorting'])

    updated = list(Dashboard.objects.filter(owning_feuser=feuser))
    return _ok({'dashboards': [_dash_to_json(d) for d in updated]})
