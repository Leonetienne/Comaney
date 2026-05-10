"""
Dashboard card API endpoints (session auth, not Bearer).

Endpoints:
    GET/POST   /budget/dashboard/cards/
    PATCH/DEL  /budget/dashboard/cards/<uid>/
    POST       /budget/dashboard/cards/reorder/
    GET        /budget/dashboard/cards/presets/
    GET        /budget/dashboard/data/          → all cards with computed data
"""

import json
from decimal import Decimal

import yaml
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from ..dashboard_cards import PRESETS, CardConfigError, compute_card_data, parse_card_config
from ..date_utils import financial_month_range, financial_year_range
from ..decorators import feuser_required
from ..models import DashboardCard, Expense
from ._period import _get_month, _get_period_mode, _get_year


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(data: dict, status: int = 200) -> JsonResponse:
    return JsonResponse(data, status=status)


def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({'error': msg}, status=status)


def _parse_body(request) -> dict:
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}


def _period_qs(request, feuser):
    """Build the period-scoped base queryset from request params."""
    mode = _get_period_mode(request)
    if mode == 'year':
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)

    return Expense.objects.filter(
        owning_feuser=feuser,
        date_due__gte=start,
        date_due__lte=end,
        deactivated=False,
    )


def _card_to_json(card: DashboardCard, period_qs, feuser) -> dict:
    """Serialise a card including its computed data for the current period."""
    try:
        config = parse_card_config(card.yaml_config)
        data = compute_card_data(config, period_qs, feuser)
        error = None
    except CardConfigError as exc:
        config = {}
        data = {}
        error = str(exc)

    pos = config.get('positioning', {}) if config else {}
    return {
        'id':          card.pk,
        'yaml_config': card.yaml_config,
        'position':    pos.get('position', 0),
        'width':       pos.get('width', 2),
        'height':      pos.get('height', 2),
        'config':      config,
        'data':        data,
        'error':       error,
    }


# ---------------------------------------------------------------------------
# Card list / create
# ---------------------------------------------------------------------------

@feuser_required
@require_http_methods(['GET', 'POST'])
def cards_api(request):
    feuser = request.feuser

    if request.method == 'GET':
        period_qs = _period_qs(request, feuser)
        cards = DashboardCard.objects.filter(owning_feuser=feuser)
        card_list = sorted(
            [_card_to_json(c, period_qs, feuser) for c in cards],
            key=lambda c: (c['position'], c['id']),
        )
        return _ok({'cards': card_list})

    # POST — create new card
    body = _parse_body(request)
    yaml_str = body.get('yaml_config', '').strip()
    if not yaml_str:
        return _err('yaml_config is required')

    try:
        config = parse_card_config(yaml_str)
    except CardConfigError as exc:
        return _err(str(exc))

    card = DashboardCard(owning_feuser=feuser, yaml_config=yaml_str)
    card.save()

    period_qs = _period_qs(request, feuser)
    return _ok({'card': _card_to_json(card, period_qs, feuser)}, status=201)


# ---------------------------------------------------------------------------
# Card detail: update / delete
# ---------------------------------------------------------------------------

@feuser_required
@require_http_methods(['PATCH', 'DELETE'])
def card_detail_api(request, uid: int):
    feuser = request.feuser
    try:
        card = DashboardCard.objects.get(pk=uid, owning_feuser=feuser)
    except DashboardCard.DoesNotExist:
        return _err('Not found', 404)

    if request.method == 'DELETE':
        card.delete()
        return _ok({'deleted': True})

    # PATCH — update yaml
    body = _parse_body(request)
    yaml_str = body.get('yaml_config', '').strip()
    if not yaml_str:
        return _err('yaml_config is required')

    try:
        config = parse_card_config(yaml_str)
    except CardConfigError as exc:
        return _err(str(exc))

    card.yaml_config = yaml_str
    card.save()

    period_qs = _period_qs(request, feuser)
    return _ok({'card': _card_to_json(card, period_qs, feuser)})


# ---------------------------------------------------------------------------
# Bulk reorder (drag-drop)
# ---------------------------------------------------------------------------

@feuser_required
@require_http_methods(['POST'])
def cards_reorder_api(request):
    feuser = request.feuser
    body = _parse_body(request)
    positions = body.get('positions', [])

    if not isinstance(positions, list):
        return _err('positions must be a list')

    cards = {c.pk: c for c in DashboardCard.objects.filter(owning_feuser=feuser)}
    for entry in positions:
        card_id = entry.get('id')
        new_pos = entry.get('position')
        if card_id not in cards or not isinstance(new_pos, int):
            continue
        card = cards[card_id]
        try:
            cfg = yaml.safe_load(card.yaml_config) or {}
            if not isinstance(cfg, dict):
                cfg = {}
            pos = cfg.get('positioning') or {}
            pos['position'] = new_pos
            cfg['positioning'] = pos
            card.yaml_config = yaml.dump(cfg, default_flow_style=False, allow_unicode=True)
            card.save(update_fields=['yaml_config'])
        except Exception:
            pass

    updated = [{'id': pk, 'yaml_config': c.yaml_config} for pk, c in cards.items()]
    return _ok({'ok': True, 'cards': updated})


# ---------------------------------------------------------------------------
# Individual card resize
# ---------------------------------------------------------------------------

@feuser_required
@require_http_methods(['PATCH'])
def card_resize_api(request, uid: int):
    feuser = request.feuser
    try:
        card = DashboardCard.objects.get(pk=uid, owning_feuser=feuser)
    except DashboardCard.DoesNotExist:
        return _err('Not found', 404)

    body = _parse_body(request)
    w = body.get('width')
    h = body.get('height')

    try:
        cfg = yaml.safe_load(card.yaml_config) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        pos = cfg.get('positioning') or {}
        if w is not None:
            pos['width']  = max(1, min(12, int(w)))
        if h is not None:
            pos['height'] = max(1, int(h))
        cfg['positioning'] = pos
        card.yaml_config = yaml.dump(cfg, default_flow_style=False, allow_unicode=True)
        card.save(update_fields=['yaml_config'])
    except Exception:
        return _err('Failed to update card')

    new_w = cfg['positioning'].get('width', 2)
    new_h = cfg['positioning'].get('height', 2)
    return _ok({'width': new_w, 'height': new_h, 'yaml_config': card.yaml_config})


# ---------------------------------------------------------------------------
# Presets list
# ---------------------------------------------------------------------------

@feuser_required
@require_http_methods(['GET'])
def card_presets_api(request):
    return _ok({'presets': [{'name': p['name'], 'yaml': p['yaml']} for p in PRESETS]})
