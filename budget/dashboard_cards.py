"""
Dashboard card YAML parsing, data computation, and sandboxed Python execution.

Card YAML schema:
    type: cell | bar-chart | pie-chart | list | line-chart | spacer
    # spacer: invisible placeholder; only positioning + hide_on are meaningful
    hide_on: mobile | desktop   # optional (spacer only); hides card on that viewport (frees grid space)
    title: "string"
    query: "query string"       # optional; filters the period queryset
    group: tags | categories    # required for bar-chart / pie-chart
    max_groups: N               # optional; top-N groups (bar-chart only)
    hide_groups: "a,b"          # optional; comma-sep group names to exclude
    method:                     # meaning depends on card type:
      cell:       sum | total | count | custom
      bar-chart / pie-chart:  sum | total
      list:       sum | total | count  (controls optional sum row)
      line-chart: base | cum           (per-bucket vs cumulative; default cum)
    flip_signs: true/false      # optional; multiply computed value/sum by -1
    color: "#hex"               # optional; cell background color (both modes)
    color_lightmode: "#hex"    # optional; overrides color in light mode
    color_darkmode: "#hex"     # optional; overrides color in dark mode
    text_color: "#hex"         # optional (cell only); text color (both modes); default white/black
    text_color_lightmode: "#hex"  # optional; overrides text_color in light mode
    text_color_darkmode: "#hex"   # optional; overrides text_color in dark mode
    color_breakpoints:          # optional (cell only); override color by computed value
      - less_than: 100          # applies when value < 100
        color: "#ffff00"
        color_lightmode: "#hex" # optional per-breakpoint mode overrides
        color_darkmode: "#hex"
      - less_than: 0
        color: "#ff0000"        # last matching breakpoint wins
    link: "/path?search=..."    # optional; clicking a cell navigates here
    link_template: "/path?search=tag%3D$GROUP_NAME"  # optional; $GROUP_NAME replaced per segment
    template: "$VALUE $CURRENCY_SYMBOL"  # optional; cell display template ($VALUE / $CURRENCY_SYMBOL)
    python: |                   # required when method=custom; function body
        return query_sum('...')
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

import ast
import threading
from decimal import Decimal, InvalidOperation

import yaml
from django.db.models import Case, DecimalField, F, Sum, When

from .query_parser import apply_query

VALID_TYPES = {'cell', 'bar-chart', 'pie-chart', 'list', 'line-chart', 'spacer'}
VALID_HIDE_ON = {'', 'mobile', 'desktop'}
VALID_GROUPS = {'tags', 'categories'}
VALID_METHODS = {'sum', 'total', 'count', 'custom'}
VALID_LIST_METHODS = {'sum', 'total', 'count'}
VALID_ORDER_BY = {'value', 'date', 'title'}
VALID_ORDER_DIR = {'asc', 'desc'}
VALID_LINE_METHODS = {'base', 'cum'}
VALID_SERIES_METHODS = {'sum', 'total'}

# Expense types that count as negative income under method=total
_TOTAL_NEGATIVE_TYPES = {'income', 'savings_wit', 'carry_over'}

DEFAULT_POSITIONING = {'position': 0, 'width': 2, 'height': 2}

# ---------------------------------------------------------------------------
# Allowed-key schemas (used by _check_unknown to reject typos)
# ---------------------------------------------------------------------------

_COMMON_KEYS = {'type', 'title', 'query', 'positioning'}

ALLOWED_KEYS = {
    'cell':       _COMMON_KEYS | {'method', 'flip_signs', 'color', 'color_lightmode',
                                   'color_darkmode', 'color_breakpoints', 'color-breakpoints',
                                   'text_color', 'text_color_lightmode', 'text_color_darkmode',
                                   'link', 'link_template', 'template', 'python'},
    'bar-chart':  _COMMON_KEYS | {'method', 'group', 'max_groups', 'hide_groups',
                                   'flip_signs', 'link_template'},
    'pie-chart':  _COMMON_KEYS | {'method', 'group', 'max_groups', 'hide_groups',
                                   'flip_signs', 'link_template'},
    'list':       _COMMON_KEYS | {'method', 'order_by', 'order_dir', 'type_colors',
                                   'show_sum', 'sum_template', 'flip_signs'},
    'line-chart': _COMMON_KEYS | {'method', 'series', 'render_type',
                                   'suggested_min', 'suggested_max',
                                   'limit_min', 'limit_max'},
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
        if method == 'custom' and not cfg.get('python', '').strip():
            raise CardConfigError("method=custom requires a 'python' code block")

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
    if card_type == 'cell':
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
        'python':        str(cfg.get('python', '')),
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
    elif method == 'custom':
        fns = _make_query_fns(period_qs, value_field=value_field)
        value = _run_sandboxed(config['python'], fns)
    else:
        value = Decimal('0')

    if invert:
        value = -value
    return {'value': float(value)}


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
        rows = (
            qs.filter(tags__isnull=False)
            .values('tags__title')
            .annotate(total=Sum(agg_field))
            .order_by('-total')
        )
        labels = [r['tags__title'] or '' for r in rows]
        values = [float(r['total']) for r in rows]

    elif group == 'categories':
        rows = (
            qs.values('category__title')
            .annotate(total=Sum(agg_field))
            .order_by('-total')
        )
        labels = [r['category__title'] if r['category__title'] else 'Uncategorized' for r in rows]
        values = [float(r['total']) for r in rows]

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
# Sandboxed Python execution for method=custom cells
# ---------------------------------------------------------------------------

_SAFE_BUILTINS = {
    '__builtins__': {},
    'abs': abs, 'round': round, 'min': min, 'max': max,
    'sum': sum, 'len': len, 'int': int, 'float': float,
    'str': str, 'bool': bool,
    'True': True, 'False': False, 'None': None,
    'Decimal': Decimal,
}

_FORBIDDEN_NODES = (ast.Import, ast.ImportFrom)


def _make_query_fns(period_qs, value_field: str = 'value') -> dict:
    def query_sum(q=''):
        qs = apply_query(period_qs, q)
        return qs.aggregate(t=Sum(value_field))['t'] or Decimal('0')

    def query_sum_abs(q=''):
        vals = list(apply_query(period_qs, q).values_list(value_field, flat=True))
        return sum(abs(v) for v in vals) if vals else Decimal('0')

    def query_sum_gt0(q=''):
        qs = apply_query(period_qs, q).filter(**{f'{value_field}__gt': 0})
        return qs.aggregate(t=Sum(value_field))['t'] or Decimal('0')

    def query_sum_lt0(q=''):
        qs = apply_query(period_qs, q).filter(**{f'{value_field}__lt': 0})
        return qs.aggregate(t=Sum(value_field))['t'] or Decimal('0')

    return {
        'query_sum':      query_sum,
        'query_sum_abs':  query_sum_abs,
        'query_sum_gt0':  query_sum_gt0,
        'query_sum_lt0':  query_sum_lt0,
    }


def _run_sandboxed(code: str, fns: dict, timeout: float = 2.0) -> Decimal:
    """Execute a user-supplied function body in a restricted environment."""
    indented = '\n'.join('    ' + line for line in code.splitlines())
    wrapped = f"def __fn__():\n{indented}\n__result__ = __fn__()"

    try:
        tree = ast.parse(wrapped, '<card>', 'exec')
    except SyntaxError as exc:
        raise CardConfigError(f"Syntax error in python block: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            raise CardConfigError("Imports are not allowed in sandboxed code")
        if isinstance(node, ast.Attribute) and isinstance(node.attr, str) and node.attr.startswith('__'):
            raise CardConfigError("Dunder attributes are not allowed in sandboxed code")

    compiled = compile(tree, '<card>', 'exec')
    ns = {**_SAFE_BUILTINS, **fns}

    result_holder: list = [None]
    error_holder:  list = [None]

    def _run():
        try:
            exec(compiled, ns)
            result_holder[0] = ns.get('__result__')
        except Exception as exc:  # noqa: BLE001
            error_holder[0] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        raise CardConfigError("Custom python block timed out (> 2 s)")
    if error_holder[0] is not None:
        raise CardConfigError(f"Runtime error in python block: {error_holder[0]}")

    raw = result_holder[0]
    if raw is None:
        return Decimal('0')
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError):
        return Decimal('0')


# ---------------------------------------------------------------------------
# Preset YAML snippets (shown in the "new card" dialog)
# ---------------------------------------------------------------------------

def _build_presets():
    from .fixtures import DEFAULT_DASHBOARD_CARDS
    result = []
    for entry in DEFAULT_DASHBOARD_CARDS:
        try:
            name = (yaml.safe_load(entry['yaml']) or {}).get('title', 'Card')
        except Exception:
            name = 'Card'
        result.append({'name': name, 'yaml': entry['yaml']})
    return result


PRESETS = _build_presets()
