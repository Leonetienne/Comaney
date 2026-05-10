"""
Dashboard card YAML parsing, data computation, and sandboxed Python execution.

Card YAML schema:
    type: cell | bar-chart | pie-chart
    title: "string"
    query: "query string"       # optional; filters the period queryset
    group: tags | categories    # required for bar-chart / pie-chart
    max_groups: N               # optional; top-N groups (bar-chart only)
    hide_groups: "a,b"          # optional; comma-sep group names to exclude
    method: sum | count | custom   # required for cell
    color: "#hex"               # optional; cell background color
    python: |                   # required when method=custom; function body
        return query_sum('...')
    positioning:
        position: N             # display order (1-based)
        width: N                # grid columns to span
        height: N               # grid rows to span
"""

import ast
import threading
from decimal import Decimal, InvalidOperation

import yaml
from django.db.models import Sum

from .query_parser import apply_query

VALID_TYPES = {'cell', 'bar-chart', 'pie-chart'}
VALID_GROUPS = {'tags', 'categories'}
VALID_METHODS = {'sum', 'count', 'custom'}

DEFAULT_POSITIONING = {'position': 0, 'width': 2, 'height': 2}


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------

class CardConfigError(ValueError):
    pass


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

    pos = cfg.get('positioning') or {}
    positioning = {
        'position': int(pos.get('position', DEFAULT_POSITIONING['position'])),
        'width':    max(1, min(12, int(pos.get('width',    DEFAULT_POSITIONING['width'])))),
        'height':   max(1, int(pos.get('height',   DEFAULT_POSITIONING['height']))),
    }

    return {
        'type':        card_type,
        'title':       str(cfg.get('title', '')),
        'query':       str(cfg.get('query', '')),
        'group':       str(cfg.get('group', '')),
        'max_groups':  int(cfg['max_groups']) if cfg.get('max_groups') is not None else None,
        'hide_groups': (
            [str(g).strip().lower() for g in cfg['hide_groups'] if str(g).strip()]
            if isinstance(cfg.get('hide_groups'), list)
            else []
        ),
        'method':      str(cfg.get('method', 'sum')),
        'color':       str(cfg.get('color', '')),
        'python':      str(cfg.get('python', '')),
        'positioning': positioning,
    }


# ---------------------------------------------------------------------------
# Data computation
# ---------------------------------------------------------------------------

def compute_card_data(config: dict, period_qs, feuser) -> dict:
    """
    Compute the display data for a card given a period queryset (already
    scoped to feuser + date range + deactivated=False).
    Returns a dict suitable for JSON serialisation.
    """
    card_type = config['type']

    if card_type == 'cell':
        return _compute_cell(config, period_qs)
    if card_type in ('bar-chart', 'pie-chart'):
        return _compute_chart(config, period_qs)
    return {}


def _filtered_qs(config: dict, base_qs):
    q = config.get('query', '').strip()
    if q:
        return apply_query(base_qs, q)
    return base_qs


def _compute_cell(config: dict, period_qs) -> dict:
    method = config['method']
    qs = _filtered_qs(config, period_qs)

    if method == 'sum':
        value = qs.aggregate(t=Sum('value'))['t'] or Decimal('0')
        return {'value': float(value)}

    if method == 'count':
        return {'value': qs.count()}

    if method == 'custom':
        fns = _make_query_fns(period_qs)
        value = _run_sandboxed(config['python'], fns)
        return {'value': float(value)}

    return {'value': 0}


def _compute_chart(config: dict, period_qs) -> dict:
    qs = _filtered_qs(config, period_qs)
    group = config['group']

    if group == 'tags':
        rows = (
            qs.filter(tags__isnull=False)
            .values('tags__title')
            .annotate(total=Sum('value'))
            .order_by('-total')
        )
        labels = [r['tags__title'] or '' for r in rows]
        values = [float(r['total']) for r in rows]

    elif group == 'categories':
        rows = (
            qs.values('category__title')
            .annotate(total=Sum('value'))
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

    return {'labels': labels, 'values': values}


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


def _make_query_fns(period_qs) -> dict:
    def query_sum(q=''):
        qs = apply_query(period_qs, q)
        return qs.aggregate(t=Sum('value'))['t'] or Decimal('0')

    def query_sum_abs(q=''):
        vals = list(apply_query(period_qs, q).values_list('value', flat=True))
        return sum(abs(v) for v in vals) if vals else Decimal('0')

    def query_sum_gt0(q=''):
        qs = apply_query(period_qs, q).filter(value__gt=0)
        return qs.aggregate(t=Sum('value'))['t'] or Decimal('0')

    def query_sum_lt0(q=''):
        qs = apply_query(period_qs, q).filter(value__lt=0)
        return qs.aggregate(t=Sum('value'))['t'] or Decimal('0')

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

PRESETS = [
    {
        'name': 'Income (cell)',
        'yaml': (
            "type: cell\n"
            "title: Income\n"
            "query: \"type=income\"\n"
            "method: sum\n"
            "color: \"#1a3326\"\n"
            "positioning:\n"
            "    position: 1\n"
            "    width: 1\n"
            "    height: 1\n"
        ),
    },
    {
        'name': 'Paid expenses (cell)',
        'yaml': (
            "type: cell\n"
            "title: Paid expenses\n"
            "query: \"type=expense settled=yes\"\n"
            "method: sum\n"
            "color: \"#331a1d\"\n"
            "positioning:\n"
            "    position: 2\n"
            "    width: 1\n"
            "    height: 1\n"
        ),
    },
    {
        'name': 'Outstanding (cell)',
        'yaml': (
            "type: cell\n"
            "title: Outstanding\n"
            "query: \"type=expense settled=no\"\n"
            "method: sum\n"
            "color: \"#331a1d\"\n"
            "positioning:\n"
            "    position: 3\n"
            "    width: 1\n"
            "    height: 1\n"
        ),
    },
    {
        'name': 'Savings (custom cell)',
        'yaml': (
            "type: cell\n"
            "title: Savings\n"
            "method: custom\n"
            "python: >\n"
            "    return query_sum('type=\"savings deposit\"')"
            " - query_sum('type=\"savings withdrawal\"')\n"
            "positioning:\n"
            "    position: 4\n"
            "    width: 1\n"
            "    height: 1\n"
        ),
    },
    {
        'name': 'Left to spend (custom cell)',
        'yaml': (
            "type: cell\n"
            "title: Left to spend\n"
            "method: custom\n"
            "color: \"#1a3326\"\n"
            "python: >\n"
            "    return (query_sum('type=\"income\"')"
            " - query_sum('type=\"expense\"')"
            " - (query_sum('type=\"savings deposit\"')"
            " + query_sum('type=\"savings withdrawal\"')))\n"
            "positioning:\n"
            "    position: 5\n"
            "    width: 1\n"
            "    height: 1\n"
        ),
    },
    {
        'name': 'Expenses by category (pie)',
        'yaml': (
            "type: pie-chart\n"
            "group: categories\n"
            "title: Expenses by category\n"
            "positioning:\n"
            "    position: 6\n"
            "    width: 3\n"
            "    height: 3\n"
        ),
    },
    {
        'name': 'Expenses by tag (bar)',
        'yaml': (
            "type: bar-chart\n"
            "group: tags\n"
            "title: Expenses by tag\n"
            "positioning:\n"
            "    position: 7\n"
            "    width: 3\n"
            "    height: 3\n"
        ),
    },
    {
        'name': 'Top 8 tags (bar)',
        'yaml': (
            "type: bar-chart\n"
            "group: tags\n"
            "title: Top 8 tags\n"
            "max_groups: 8\n"
            "positioning:\n"
            "    position: 8\n"
            "    width: 3\n"
            "    height: 3\n"
        ),
    },
    {
        'name': 'Expenses count (cell)',
        'yaml': (
            "type: cell\n"
            "title: Expense count\n"
            "query: \"type=expense\"\n"
            "method: count\n"
            "positioning:\n"
            "    position: 9\n"
            "    width: 1\n"
            "    height: 1\n"
        ),
    },
]
