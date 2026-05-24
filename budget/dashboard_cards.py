"""
Dashboard card YAML parsing, data computation, and sandboxed Python execution.

Card YAML schema:
    type: cell | bar-chart | pie-chart | list | line-chart | gauge | spacer
    # spacer: invisible placeholder; only positioning + hide_on are meaningful
    hide_on: mobile | desktop   # optional (spacer only); hides card on that viewport (frees grid space)
    title: "string"
    query: "query string"       # optional; filters the period queryset (required for gauge)
    group: tags | categories    # required for bar-chart / pie-chart
    max_groups: N               # optional; top-N groups (bar-chart only)
    hide_groups: "a,b"          # optional; comma-sep group names to exclude
    method:                     # meaning depends on card type:
      cell:       sum | total | count
      bar-chart / pie-chart:  sum | total
      list:       sum | total | count  (controls optional sum row)
      line-chart: base | cum           (per-bucket vs cumulative; default cum)
      gauge:      sum | total | count  (required; computes the gauge's current value)
    flip_signs: true/false      # optional; multiply computed value/sum by -1
    color: "#hex"               # optional; cell background color (both modes)
    color_lightmode: "#hex"    # optional; overrides color in light mode
    color_darkmode: "#hex"     # optional; overrides color in dark mode
    text_color: "#hex"         # optional (cell only); text color (both modes); default white/black
    text_color_lightmode: "#hex"  # optional; overrides text_color in light mode
    text_color_darkmode: "#hex"   # optional; overrides text_color in dark mode
    color_breakpoints:          # optional (cell, gauge); override color by computed value
      - less_than: 100          # cell: applies when value < 100; gauge: when percent-of-max < 100
        color: "#ffff00"
        color_lightmode: "#hex" # optional per-breakpoint mode overrides
        color_darkmode: "#hex"
      - less_than: 0
        color: "#ff0000"        # last matching breakpoint wins
    link: "/path?search=..."    # optional; clicking a cell/gauge navigates here
    link_template: "/path?search=tag%3D$GROUP_NAME"  # optional; $GROUP_NAME replaced per segment
    template: "$VALUE $CURRENCY_SYMBOL"  # optional; cell display template ($VALUE / $CURRENCY_SYMBOL)
    # gauge-only fields:
    max_value: N                 # fixed gauge maximum; mutually exclusive with max_value_query
    max_value_query: "query"     # dynamic gauge maximum; requires max_value_method
    max_value_method: sum | total | count
    gauge_color: "#hex"          # optional; arc + value-text color (both modes); default neutral grey
    gauge_color_lightmode: "#hex"
    gauge_color_darkmode: "#hex"
    show_raw_values: true/false  # optional; show "value / max CURRENCY" text; default true
    show_percent: true/false     # optional; show "NN%" text; default true (not mutually exclusive)
    # list-only fields:
    order_by: value | date | title   # sort field; default date
    order_dir: asc | desc            # sort direction; default desc
    type_colors: true/false          # colour rows by expense type; default true
    show_sum: true/false             # show computed sum row at top; default false
    sum_template: "$VALUE $CURRENCY_SYMBOL"  # template for the sum row
    # line-chart fields:
    render_type: smooth | linear    # optional; line interpolation; default smooth
    suggested_min: 0                # optional float; soft lower bound; expands if data goes lower
    suggested_max: 100              # optional float; soft upper bound; expands if data goes higher
    limit_min: -50                   # optional float; hard lower cap; clips data below
    limit_max: 200                   # optional float; hard upper cap; clips data above
    series:                     # required; list of data series
      - label: "Series name"
        query: "..."            # optional; additional filter per series
        method: sum | total     # per-series aggregation; default sum
        color: "#hex"           # optional; derived from label if omitted
    positioning:
        position: N             # display order (1-based)
        width: N                # grid columns to span
        height: N               # grid rows to span
        mobile:                 # optional; overrides above on mobile (≤ 6-col grid)
            position: N
            width: N            # clamped to 1–6
            height: N
"""

from decimal import Decimal, InvalidOperation

import yaml
from django.db.models import Case, DecimalField, F, Sum, When

from .query_parser import apply_query, has_date_filter

VALID_TYPES = {'cell', 'bar-chart', 'pie-chart', 'list', 'line-chart', 'gauge', 'spacer'}
VALID_HIDE_ON = {'', 'mobile', 'desktop'}
VALID_GROUPS = {'tags', 'categories'}
VALID_METHODS = {'sum', 'total', 'count'}
VALID_LIST_METHODS = {'sum', 'total', 'count'}
VALID_ORDER_BY = {'value', 'date', 'title'}
VALID_ORDER_DIR = {'asc', 'desc'}
VALID_LINE_METHODS = {'base', 'cum'}
VALID_SERIES_METHODS = {'sum', 'total'}

# Expense types that count as negative income under method=total
_TOTAL_NEGATIVE_TYPES = {'income', 'savings_wit'}

DEFAULT_POSITIONING = {'position': 0, 'width': 2, 'height': 2}

# ---------------------------------------------------------------------------
# Allowed-key schemas (used by _check_unknown to reject typos)
# ---------------------------------------------------------------------------

_COMMON_KEYS = {'type', 'title', 'query', 'positioning'}

ALLOWED_KEYS = {
    'cell':       _COMMON_KEYS | {'method', 'flip_signs', 'color', 'color_lightmode',
                                   'color_darkmode', 'color_breakpoints', 'color-breakpoints',
                                   'text_color', 'text_color_lightmode', 'text_color_darkmode',
                                   'link', 'link_template', 'template'},
    'bar-chart':  _COMMON_KEYS | {'method', 'group', 'max_groups', 'hide_groups',
                                   'flip_signs', 'link_template'},
    'pie-chart':  _COMMON_KEYS | {'method', 'group', 'max_groups', 'hide_groups',
                                   'flip_signs', 'link_template'},
    'list':       _COMMON_KEYS | {'method', 'order_by', 'order_dir', 'type_colors',
                                   'show_sum', 'sum_template', 'flip_signs'},
    'line-chart': _COMMON_KEYS | {'method', 'series', 'render_type',
                                   'suggested_min', 'suggested_max',
                                   'limit_min', 'limit_max'},
    'gauge':      _COMMON_KEYS | {'method', 'max_value', 'max_value_query', 'max_value_method',
                                   'gauge_color', 'gauge_color_lightmode', 'gauge_color_darkmode',
                                   'color_breakpoints', 'color-breakpoints',
                                   'show_raw_values', 'show_percent', 'link'},
    'spacer':     {'type', 'positioning', 'hide_on'},
}

ALLOWED_SERIES_KEYS       = {'label', 'query', 'method', 'color', 'flip_signs', 'link_template'}
ALLOWED_BREAKPOINT_KEYS   = {'less_than', 'color', 'color_lightmode', 'color_darkmode',
                             'text_color', 'text_color_lightmode', 'text_color_darkmode'}
ALLOWED_POSITIONING_KEYS  = {'position', 'width', 'height', 'mobile'}
ALLOWED_MOBILE_KEYS       = {'position', 'width', 'height'}


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------

class CardConfigError(ValueError):
    pass


def _check_unknown(mapping: dict, allowed: set, context: str) -> None:
    unknown = set(mapping.keys()) - allowed
    if unknown:
        raise CardConfigError(f"{context}: unknown field(s): {', '.join(sorted(unknown))}")


def parse_card_config(yaml_str: str) -> dict:
    """Parse and validate card YAML. Returns a normalized config dict."""
    try:
        cfg = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise CardConfigError(f"Invalid YAML: {e}") from e

    if not isinstance(cfg, dict):
        raise CardConfigError("Card config must be a YAML mapping")

    card_type = cfg.get('type', '')
    if card_type not in VALID_TYPES:
        raise CardConfigError(f"type must be one of: {', '.join(sorted(VALID_TYPES))}")

    _check_unknown(cfg, ALLOWED_KEYS[card_type], 'card')

    if card_type in ('bar-chart', 'pie-chart'):
        group = cfg.get('group', '')
        if group not in VALID_GROUPS:
            raise CardConfigError(f"group must be one of: {', '.join(sorted(VALID_GROUPS))}")

    if card_type == 'cell':
        method = cfg.get('method', 'sum')
        if method not in VALID_METHODS:
            raise CardConfigError(f"method must be one of: {', '.join(sorted(VALID_METHODS))}")

    if card_type == 'gauge':
        method = cfg.get('method')
        if method not in VALID_METHODS:
            raise CardConfigError(f"gauge requires a method, one of: {', '.join(sorted(VALID_METHODS))}")
        if not str(cfg.get('query', '')).strip():
            raise CardConfigError("gauge requires a 'query'")

        has_fixed_max = cfg.get('max_value') is not None
        has_dynamic_max = bool(str(cfg.get('max_value_query', '')).strip())
        if has_fixed_max and has_dynamic_max:
            raise CardConfigError("gauge: specify either max_value or max_value_query, not both")
        if not has_fixed_max and not has_dynamic_max:
            raise CardConfigError("gauge: requires either max_value or max_value_query + max_value_method")
        if has_fixed_max:
            try:
                max_value_num = float(cfg['max_value'])
            except (TypeError, ValueError):
                raise CardConfigError("max_value must be a number")
            if max_value_num <= 0:
                raise CardConfigError("max_value must be greater than 0")
        if has_dynamic_max:
            max_value_method = cfg.get('max_value_method')
            if max_value_method not in VALID_METHODS:
                raise CardConfigError(
                    f"gauge: max_value_method must be one of: {', '.join(sorted(VALID_METHODS))}"
                )

    if card_type == 'list':
        order_by = cfg.get('order_by', 'date')
        if str(order_by) not in VALID_ORDER_BY:
            raise CardConfigError(f"order_by must be one of: {', '.join(sorted(VALID_ORDER_BY))}")
        order_dir = cfg.get('order_dir', 'desc')
        if str(order_dir) not in VALID_ORDER_DIR:
            raise CardConfigError("order_dir must be asc or desc")
        method = cfg.get('method', 'sum')
        if str(method) not in VALID_LIST_METHODS:
            raise CardConfigError(f"method for list must be one of: {', '.join(sorted(VALID_LIST_METHODS))}")

    hide_on = ''
    if card_type == 'spacer':
        hide_on = str(cfg.get('hide_on', ''))
        if hide_on not in VALID_HIDE_ON:
            raise CardConfigError("hide_on must be mobile, desktop, or omitted")

    color_breakpoints = []
    if card_type in ('cell', 'gauge'):
        raw_bp = cfg.get('color_breakpoints') or cfg.get('color-breakpoints') or []
        if not isinstance(raw_bp, list):
            raise CardConfigError("color_breakpoints must be a list")
        for i, bp in enumerate(raw_bp):
            if not isinstance(bp, dict):
                raise CardConfigError(f"color_breakpoints[{i}] must be a mapping")
            _check_unknown(bp, ALLOWED_BREAKPOINT_KEYS, f"color_breakpoints[{i}]")
            if 'less_than' not in bp:
                raise CardConfigError(f"color_breakpoints[{i}] must have a 'less_than' key")
            try:
                less_than = float(bp['less_than'])
            except (TypeError, ValueError):
                raise CardConfigError(f"color_breakpoints[{i}].less_than must be a number")
            color_breakpoints.append({
                'less_than':            less_than,
                'color':                str(bp.get('color', '')),
                'color_lightmode':      str(bp.get('color_lightmode', '')),
                'color_darkmode':       str(bp.get('color_darkmode', '')),
                'text_color':           str(bp.get('text_color', '')),
                'text_color_lightmode': str(bp.get('text_color_lightmode', '')),
                'text_color_darkmode':  str(bp.get('text_color_darkmode', '')),
            })

    if card_type in ('bar-chart', 'pie-chart'):
        method = cfg.get('method', 'sum')
        if method not in ('sum', 'total'):
            raise CardConfigError("method for charts must be sum or total")

    series = []
    render_type = 'smooth'
    ranges = {}
    if card_type == 'line-chart':
        method = cfg.get('method', 'cum')
        if str(method) not in VALID_LINE_METHODS:
            raise CardConfigError("method for line-chart must be base or cum")
        raw_series = cfg.get('series', [])
        if not isinstance(raw_series, list) or not raw_series:
            raise CardConfigError("line-chart requires at least one series")
        for i, s in enumerate(raw_series):
            if not isinstance(s, dict):
                raise CardConfigError(f"series[{i}] must be a mapping")
            _check_unknown(s, ALLOWED_SERIES_KEYS, f"series[{i}]")
            label = str(s.get('label', '')).strip()
            if not label:
                raise CardConfigError(f"series[{i}] must have a label")
            s_method = str(s.get('method', 'sum'))
            if s_method not in VALID_SERIES_METHODS:
                raise CardConfigError(f"series[{i}].method must be sum or total")
            series.append({
                'label':         label,
                'color':         str(s.get('color', '')),
                'query':         str(s.get('query', '')),
                'method':        s_method,
                'flip_signs':    bool(s.get('flip_signs', False)),
                'link_template': str(s.get('link_template', '')),
            })

        render_type = str(cfg.get('render_type', 'smooth'))
        if render_type not in ('smooth', 'linear'):
            raise CardConfigError("render_type must be smooth or linear")

        ranges = {}
        for key in ('suggested_min', 'suggested_max', 'limit_min', 'limit_max'):
            if cfg.get(key) is not None:
                try:
                    ranges[key] = float(cfg[key])
                except (TypeError, ValueError):
                    raise CardConfigError(f"{key} must be a number")

        r = ranges
        if 'suggested_min' in r and 'suggested_max' in r and r['suggested_min'] >= r['suggested_max']:
            raise CardConfigError("suggested_min must be less than suggested_max")
        if 'limit_min' in r and 'limit_max' in r and r['limit_min'] >= r['limit_max']:
            raise CardConfigError("limit_min must be less than limit_max")
        if 'suggested_max' in r and 'limit_max' in r and r['suggested_max'] > r['limit_max']:
            raise CardConfigError("suggested_max cannot exceed limit_max")
        if 'suggested_min' in r and 'limit_min' in r and r['suggested_min'] < r['limit_min']:
            raise CardConfigError("suggested_min cannot be below limit_min")
        if 'limit_min' in r and 'suggested_max' in r and r['limit_min'] >= r['suggested_max']:
            raise CardConfigError("limit_min must be less than suggested_max")
        if 'suggested_min' in r and 'limit_max' in r and r['suggested_min'] >= r['limit_max']:
            raise CardConfigError("suggested_min must be less than limit_max")

    pos = cfg.get('positioning') or {}
    if isinstance(pos, dict):
        _check_unknown(pos, ALLOWED_POSITIONING_KEYS, 'positioning')
    mobile_pos = pos.get('mobile') if isinstance(pos, dict) else None
    mobile_positioning = {}
    if isinstance(mobile_pos, dict):
        _check_unknown(mobile_pos, ALLOWED_MOBILE_KEYS, 'positioning.mobile')
        if 'position' in mobile_pos:
            mobile_positioning['position'] = int(mobile_pos['position'])
        if 'width' in mobile_pos:
            mobile_positioning['width'] = max(1, min(6, int(mobile_pos['width'])))
        if 'height' in mobile_pos:
            mobile_positioning['height'] = max(1, int(mobile_pos['height']))
    positioning = {
        'position': int(pos.get('position', DEFAULT_POSITIONING['position'])),
        'width':    max(1, min(12, int(pos.get('width',    DEFAULT_POSITIONING['width'])))),
        'height':   max(1, int(pos.get('height',   DEFAULT_POSITIONING['height']))),
        'mobile':   mobile_positioning,
    }

    return {
        'type':          card_type,
        'title':         str(cfg.get('title', '')),
        'query':         str(cfg.get('query', '')),
        'group':         str(cfg.get('group', '')),
        'max_groups':    int(cfg['max_groups']) if cfg.get('max_groups') is not None else None,
        'hide_groups':   (
            [str(g).strip().lower() for g in cfg['hide_groups'] if str(g).strip()]
            if isinstance(cfg.get('hide_groups'), list)
            else []
        ),
        'method':        str(cfg.get('method', 'sum')),
        'flip_signs':    bool(cfg.get('flip_signs', False)),
        'color':               str(cfg.get('color', '')),
        'color_lightmode':     str(cfg.get('color_lightmode', '')),
        'color_darkmode':      str(cfg.get('color_darkmode', '')),
        'text_color':          str(cfg.get('text_color', '')),
        'text_color_lightmode': str(cfg.get('text_color_lightmode', '')),
        'text_color_darkmode':  str(cfg.get('text_color_darkmode', '')),
        'color_breakpoints':   color_breakpoints,
        'link':             str(cfg.get('link', '')),
        'link_template':    str(cfg.get('link_template', '')),
        'template':         str(cfg.get('template', '')),
        # list-only fields
        'order_by':      str(cfg.get('order_by', 'date')),
        'order_dir':     str(cfg.get('order_dir', 'desc')),
        'type_colors':   cfg.get('type_colors', True) is not False,
        'show_sum':      bool(cfg.get('show_sum', False)),
        'sum_template':  str(cfg.get('sum_template', '')),
        # line-chart fields
        'series':        series,
        'render_type':   render_type,
        'suggested_min': ranges.get('suggested_min'),
        'suggested_max': ranges.get('suggested_max'),
        'limit_min':      ranges.get('limit_min'),
        'limit_max':      ranges.get('limit_max'),
        # gauge-only fields
        'max_value':             float(cfg['max_value']) if cfg.get('max_value') is not None else None,
        'max_value_query':       str(cfg.get('max_value_query', '')),
        'max_value_method':      str(cfg.get('max_value_method', '')),
        'gauge_color':           str(cfg.get('gauge_color', '')),
        'gauge_color_lightmode': str(cfg.get('gauge_color_lightmode', '')),
        'gauge_color_darkmode':  str(cfg.get('gauge_color_darkmode', '')),
        'show_raw_values':       bool(cfg.get('show_raw_values', True)),
        'show_percent':          bool(cfg.get('show_percent', True)),
        'positioning':   positioning,
        'hide_on':       hide_on,
    }


# ---------------------------------------------------------------------------
# Data computation
# ---------------------------------------------------------------------------

def compute_card_data(config: dict, period_qs, feuser, period_info: dict = None,
                      value_field: str = 'value') -> dict:
    """
    Compute the display data for a card given a period queryset (already
    scoped to feuser + date range + deactivated=False).
    Returns a dict suitable for JSON serialisation.
    period_info is {'start': date, 'end': date, 'mode': 'month'|'year'};
    required for line-chart cards.
    value_field: 'value' for personal mode, 'effective_value' for shared mode.
    """
    # If the card's own query contains date operators, use an unfiltered queryset
    # so the card's date range overrides the UI date range.
    if has_date_filter(config.get('query', '')):
        if value_field == 'effective_value':
            from .views._sharing import build_shared_qs
            period_qs = build_shared_qs(feuser, None, None)
        else:
            period_qs = period_qs.model.objects.filter(
                owning_feuser=feuser,
                deactivated=False,
                is_dummy=False,
            )

    card_type = config['type']

    if card_type == 'spacer':
        return {}
    if card_type == 'cell':
        return _compute_cell(config, period_qs, value_field=value_field, feuser=feuser)
    if card_type in ('bar-chart', 'pie-chart'):
        return _compute_chart(config, period_qs, value_field=value_field, feuser=feuser)
    if card_type == 'list':
        return _compute_list(config, period_qs, value_field=value_field, feuser=feuser)
    if card_type == 'line-chart':
        if not period_info:
            return {'labels': [], 'series': []}
        return _compute_line_chart(config, period_qs, period_info, value_field=value_field, feuser=feuser)
    if card_type == 'gauge':
        return _compute_gauge(config, period_qs, value_field=value_field, feuser=feuser)
    return {}


def _filtered_qs(config: dict, base_qs, feuser=None):
    q = config.get('query', '').strip()
    if q:
        return apply_query(base_qs, q, feuser=feuser)
    return base_qs


def _signed_sum(qs, value_field: str = 'value'):
    """Sum values, negating income and savings-withdrawal types (method=total)."""
    return (
        qs.annotate(
            _signed=Case(
                When(type__in=_TOTAL_NEGATIVE_TYPES, then=-F(value_field)),
                default=F(value_field),
                output_field=DecimalField(),
            )
        ).aggregate(t=Sum('_signed'))['t'] or Decimal('0')
    )


def _compute_cell(config: dict, period_qs, value_field: str = 'value', feuser=None) -> dict:
    method = config['method']
    invert = config.get('flip_signs', False)
    qs = _filtered_qs(config, period_qs, feuser=feuser)

    if method == 'sum':
        value = qs.aggregate(t=Sum(value_field))['t'] or Decimal('0')
    elif method == 'total':
        value = _signed_sum(qs, value_field=value_field)
    elif method == 'count':
        return {'value': qs.count()}
    else:
        value = Decimal('0')

    if invert:
        value = -value
    return {'value': float(value)}


def _aggregate_by_method(qs, method: str, value_field: str = 'value') -> Decimal:
    """Shared sum/total/count aggregation, used for gauge's current and max values."""
    if method == 'sum':
        return qs.aggregate(t=Sum(value_field))['t'] or Decimal('0')
    if method == 'total':
        return _signed_sum(qs, value_field=value_field)
    if method == 'count':
        return Decimal(str(qs.count()))
    return Decimal('0')


def _compute_gauge(config: dict, period_qs, value_field: str = 'value', feuser=None) -> dict:
    qs = _filtered_qs(config, period_qs, feuser=feuser)
    value = _aggregate_by_method(qs, config['method'], value_field=value_field)

    if config.get('max_value') is not None:
        max_value = Decimal(str(config['max_value']))
    else:
        max_qs = period_qs
        # Same date-filter override as compute_card_data, applied independently to
        # max_value_query so a dynamic max can span all history, not just the UI period.
        if has_date_filter(config.get('max_value_query', '')):
            if value_field == 'effective_value':
                from .views._sharing import build_shared_qs
                max_qs = build_shared_qs(feuser, None, None)
            else:
                max_qs = max_qs.model.objects.filter(
                    owning_feuser=feuser,
                    deactivated=False,
                    is_dummy=False,
                )
        max_query = config.get('max_value_query', '').strip()
        if max_query:
            max_qs = apply_query(max_qs, max_query, feuser=feuser)
        max_value = _aggregate_by_method(max_qs, config['max_value_method'], value_field=value_field)

    value_f = float(value)
    max_value_f = float(max_value)
    percent = (value_f / max_value_f * 100) if max_value_f > 0 else 0.0

    return {'value': value_f, 'max_value': max_value_f, 'percent': percent}


def _compute_chart(config: dict, period_qs, value_field: str = 'value', feuser=None) -> dict:
    qs = _filtered_qs(config, period_qs, feuser=feuser)
    group = config['group']
    method = config.get('method', 'sum')
    invert = config.get('flip_signs', False)

    if method == 'total':
        qs = qs.annotate(
            _signed=Case(
                When(type__in=_TOTAL_NEGATIVE_TYPES, then=-F(value_field)),
                default=F(value_field),
                output_field=DecimalField(),
            )
        )
        agg_field = '_signed'
    else:
        agg_field = value_field

    if group == 'tags':
        totals: dict[str, Decimal] = {}
        # Own expenses: tags on the expense belong to feuser
        for row in (qs.filter(owning_feuser=feuser, tags__isnull=False)
                       .values('tags__title')
                       .annotate(total=Sum(agg_field))):
            t = row['tags__title'] or ''
            totals[t] = totals.get(t, Decimal('0')) + (row['total'] or Decimal('0'))
        # Foreign expenses: use the viewer's overlay tags instead
        for row in (qs.exclude(owning_feuser=feuser)
                       .filter(data_overlays__feuser=feuser,
                               data_overlays__tags__isnull=False)
                       .values('data_overlays__tags__title')
                       .annotate(total=Sum(agg_field))):
            t = row['data_overlays__tags__title'] or ''
            totals[t] = totals.get(t, Decimal('0')) + (row['total'] or Decimal('0'))
        pairs = sorted(totals.items(), key=lambda x: -x[1])
        labels = [p[0] for p in pairs]
        values = [float(p[1]) for p in pairs]

    elif group == 'categories':
        totals_cat: dict[str | None, Decimal] = {}
        # Own expenses: category on the expense belongs to feuser
        for row in (qs.filter(owning_feuser=feuser)
                       .values('category__title')
                       .annotate(total=Sum(agg_field))):
            t = row['category__title']
            totals_cat[t] = totals_cat.get(t, Decimal('0')) + (row['total'] or Decimal('0'))
        # Foreign expenses with overlay: use overlay category (may be None → Uncategorized)
        for row in (qs.exclude(owning_feuser=feuser)
                       .filter(data_overlays__feuser=feuser)
                       .values('data_overlays__category__title')
                       .annotate(total=Sum(agg_field))):
            t = row['data_overlays__category__title']
            totals_cat[t] = totals_cat.get(t, Decimal('0')) + (row['total'] or Decimal('0'))
        # Foreign expenses with no overlay at all → Uncategorized
        no_overlay = (
            qs.exclude(owning_feuser=feuser)
            .exclude(data_overlays__feuser=feuser)
            .aggregate(total=Sum(agg_field))['total']
        )
        if no_overlay:
            totals_cat[None] = totals_cat.get(None, Decimal('0')) + no_overlay
        pairs_cat = sorted(totals_cat.items(), key=lambda x: -x[1])
        labels = [p[0] if p[0] is not None else 'Uncategorized' for p in pairs_cat]
        values = [float(p[1]) for p in pairs_cat]

    else:
        return {'labels': [], 'values': []}

    # Filter out hidden groups
    hide = set(config.get('hide_groups') or [])
    if hide:
        pairs = [(l, v) for l, v in zip(labels, values) if l.lower() not in hide]
        labels, values = ([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else ([], [])

    # Limit to top-N (bar-chart only)
    max_g = config.get('max_groups')
    if max_g and config['type'] == 'bar-chart':
        labels = labels[:max_g]
        values = values[:max_g]

    if invert:
        values = [-v for v in values]

    return {'labels': labels, 'values': values}


_ORDER_BY_FIELD = {'value': 'value', 'date': 'date_due', 'title': 'title'}


def _compute_list(config: dict, period_qs, value_field: str = 'value', feuser=None) -> dict:
    qs = _filtered_qs(config, period_qs, feuser=feuser)

    order_by  = config.get('order_by', 'date')
    order_dir = config.get('order_dir', 'desc')
    if order_by == 'value':
        db_field = value_field
    else:
        db_field = _ORDER_BY_FIELD.get(order_by, 'date_due')
    order_field = db_field if order_dir == 'asc' else f'-{db_field}'
    ordered_qs = qs.order_by(order_field)

    items = [
        {
            'type':  row['type'],
            'title': row['title'],
            'value': float(row[value_field]),
        }
        for row in ordered_qs.values('uid', 'date_due', 'type', 'title', value_field)
    ]

    result: dict = {'items': items}

    if config.get('show_sum'):
        method = config.get('method', 'sum')
        invert = config.get('flip_signs', False)

        if method == 'sum':
            sum_val = qs.aggregate(t=Sum(value_field))['t'] or Decimal('0')
        elif method == 'total':
            sum_val = _signed_sum(qs, value_field=value_field)
        elif method == 'count':
            sum_val = Decimal(str(qs.count()))
        else:
            sum_val = Decimal('0')

        if invert:
            sum_val = -sum_val

        result['sum_value'] = float(sum_val)

    return result


def _compute_line_chart(config: dict, period_qs, period_info: dict,
                        value_field: str = 'value', feuser=None) -> dict:
    from collections import defaultdict
    from datetime import date, timedelta

    method     = config.get('method', 'cum')   # 'base' or 'cum'
    series_cfg = config.get('series', [])

    p_start = period_info['start']
    p_end   = period_info['end']
    p_mode  = period_info['mode']
    today   = date.today()
    cutoff  = min(p_end, today)

    # Build time buckets
    if p_mode == 'month':
        buckets = []
        d = p_start
        while d <= cutoff:
            buckets.append((d, d))
            d += timedelta(days=1)
    else:
        buckets = []
        d = p_start
        while d <= cutoff:
            b_end = min(d + timedelta(days=6), cutoff)
            buckets.append((d, b_end))
            d += timedelta(days=7)

    if not buckets:
        return {'labels': [], 'series': []}

    labels        = [b[1].isoformat() for b in buckets]
    bucket_starts = [b[0].isoformat() for b in buckets]

    base_qs = _filtered_qs(config, period_qs, feuser=feuser)

    result_series = []
    for sc in series_cfg:
        s_method = sc.get('method', 'sum')
        s_query  = sc.get('query', '').strip()

        qs = base_qs
        if s_query:
            qs = apply_query(qs, s_query, feuser=feuser)

        if s_method == 'total':
            rows = list(qs.values('date_due', 'type', value_field))
            def _signed(row, _vf=value_field):
                v = row[_vf]
                return -v if row['type'] in _TOTAL_NEGATIVE_TYPES else v
            by_date: dict = defaultdict(Decimal)
            for row in rows:
                by_date[row['date_due']] += _signed(row)
        else:
            rows = list(qs.values('date_due', value_field))
            by_date = defaultdict(Decimal)
            for row in rows:
                by_date[row['date_due']] += row[value_field]

        invert = sc.get('flip_signs', False)
        cumulative = Decimal('0')
        values = []
        for (b_start, b_end) in buckets:
            bucket_sum = sum(
                (v for dt, v in by_date.items() if b_start <= dt <= b_end),
                Decimal('0'),
            )
            if method == 'cum':
                cumulative += bucket_sum
                values.append(float(-cumulative if invert else cumulative))
            else:
                values.append(float(-bucket_sum if invert else bucket_sum))

        result_series.append({
            'label':  sc.get('label', ''),
            'color':  sc.get('color', ''),
            'values': values,
        })

    return {'labels': labels, 'bucket_starts': bucket_starts, 'series': result_series}


# ---------------------------------------------------------------------------
# Preset YAML snippets (shown in the "new card" dialog)
# ---------------------------------------------------------------------------

def _build_presets():
    from .fixtures import PREDEFINED_DASHBOARD_CARDS
    result = []
    for entry in PREDEFINED_DASHBOARD_CARDS.values():
        try:
            name = (yaml.safe_load(entry['yaml']) or {}).get('title', 'Card')
        except Exception:
            name = 'Card'
        result.append({'name': name, 'yaml': entry['yaml']})
    return result


PRESETS = _build_presets()
