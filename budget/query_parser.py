"""
Expense search query parser.

Parses the same query language understood by the client-side JS filter and
translates it into Django Q objects so the backend can apply it to an
Expense queryset.

Grammar (mirrors JS):
    expr  = group ('||' group)*
    group = atom*
    atom  = '!' atom | '(' expr ')' | filter

Filters:
    type=income / type=expense / type="savings deposit" / …
    settled=yes|no|true|false|1|0
    deactivated=yes|no|true|false|1|0
    value<N, value<=N, value>N, value>=N, value=N, value==N
    date<dd.mm.yyyy   date>=mm/dd/yyyy  date==yyyy-mm-dd  date>today
        dot delimiter → dd.mm.yyyy  |  slash delimiter → mm/dd/yyyy  |  hyphen → yyyy-mm-dd
        'today' resolves to the current date at query time
    cat=<substring>   cat=none  (expenses with no category)
    tag=<substring>   tag=none  (expenses with no tag)
    payee=<substring>
    <bare word or "quoted phrase">  →  free-text (title / payee / note)
    !<atom>           →  NOT  (negates the next atom or parenthesised group)
"""

import re
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from django.db.models import Q


# Map the lowercased display names (as used in the UI) to internal DB values.
_TYPE_MAP: dict[str, str] = {
    "income":             "income",
    "expense":            "expense",
    "savings deposit":    "savings_dep",
    "savings withdrawal": "savings_wit",
    "carry-over":         "carry_over",
    "carry over":         "carry_over",
    # Also accept internal codes directly.
    "savings_dep":        "savings_dep",
    "savings_wit":        "savings_wit",
    "carry_over":         "carry_over",
}

_TOKEN_RE = re.compile(
    r'\|\|'                                                        # ||
    r'|!'                                                          # ! (NOT)
    r'|\('                                                         # (
    r'|\)'                                                         # )
    r'|(\w+)\s*(==|[<>]=?)\s*(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./]\d{1,2}[./]\d{4}|today)'  # g1-3: key op date
    r'|(\w+)\s*(==|[<>]=?)\s*(\d+(?:\.\d+)?)'                    # g4-6: key op num
    r'|(\w+)=(?:"([^"]*)"|([^\s()|"!]+))'                        # g7-9: key="v" or key=v
    r'|"([^"]*)"'                                                  # g10:  "quoted phrase"
    r'|([^\s()|"!]+)'                                             # g11:  bare word
)


def _tokenize(raw: str) -> list[dict]:
    out: list[dict] = []
    for m in _TOKEN_RE.finditer(raw):
        s = m.group(0)
        if s == '||':
            out.append({'t': 'or'})
        elif s == '!':
            out.append({'t': 'not'})
        elif s == '(':
            out.append({'t': 'lp'})
        elif s == ')':
            out.append({'t': 'rp'})
        elif m.group(1):
            out.append({'t': 'date_cmp', 'key': m.group(1), 'op': m.group(2), 'raw': m.group(3)})
        elif m.group(4):
            out.append({'t': 'cmp', 'key': m.group(4), 'op': m.group(5), 'num': float(m.group(6))})
        elif m.group(7):
            val = m.group(8) if m.group(8) is not None else (m.group(9) or '')
            out.append({'t': 'kv', 'key': m.group(7), 'val': val})
        elif m.group(10) is not None:
            out.append({'t': 'str', 'val': m.group(10)})
        else:
            out.append({'t': 'str', 'val': m.group(11) or ''})
    return out


# ---------------------------------------------------------------------------
# Q-object builders
# ---------------------------------------------------------------------------

def _type_q(val: str) -> Q:
    internal = _TYPE_MAP.get(val)
    return Q(type=internal) if internal else Q(type=val)


def _bool_q(field: str, val: str) -> Q:
    return Q(**{field: val in ('true', 'yes', '1')})


def _value_q(op: str, num: float) -> Q:
    try:
        d = Decimal(str(num))
    except InvalidOperation:
        return Q(pk__in=[])
    lookup = {'<': 'lt', '<=': 'lte', '>': 'gt', '>=': 'gte', '=': 'exact', '==': 'exact'}.get(op, 'exact')
    return Q(**{f'value__{lookup}': d})


def _parse_date(raw: str) -> _date:
    """Parse 'today', yyyy-mm-dd (hyphen), dd.mm.yyyy (dot), or mm/dd/yyyy (slash)."""
    if raw == 'today':
        return _date.today()
    if raw[4:5] == '-':             # yyyy-mm-dd
        year, month, day = raw.split('-')
    elif '.' in raw:                # dd.mm.yyyy
        day, month, year = raw.split('.')
    else:                           # mm/dd/yyyy
        month, day, year = raw.split('/')
    return _date(int(year), int(month), int(day))


def _date_q(op: str, raw: str) -> Q:
    try:
        d = _parse_date(raw)
    except (ValueError, TypeError):
        return Q(pk__in=[])   # invalid date → match nothing
    lookup = {'<': 'lt', '<=': 'lte', '>': 'gt', '>=': 'gte', '=': 'exact', '==': 'exact'}.get(op, 'exact')
    return Q(**{f'date_due__{lookup}': d})


def _term_q(val: str) -> Q:
    return Q(title__icontains=val) | Q(payee__icontains=val) | Q(note__icontains=val)


# ---------------------------------------------------------------------------
# Filter dispatch tables
# ---------------------------------------------------------------------------

_EQUALS: dict = {
    'type':        lambda v: _type_q(v),
    'settled':     lambda v: _bool_q('settled', v),
    'deactivated': lambda v: _bool_q('deactivated', v),
    'value':       lambda v: _value_q('=', float(v)),
    'date':        lambda v: _date_q('=', v),
    'tag':         lambda v: Q(tags__isnull=True) if v == 'none' else Q(tags__title__icontains=v),
    'cat':         lambda v: Q(category__isnull=True) if v == 'none' else Q(category__title__icontains=v),
    'payee':       lambda v: Q(payee__icontains=v),
}

_CMP: dict = {
    'value': lambda op, num: _value_q(op, num),
}

_DATE_CMP: dict = {
    'date':     lambda op, raw: _date_q(op, raw),
}


# ---------------------------------------------------------------------------
# Recursive-descent compiler
# ---------------------------------------------------------------------------

def _compile(tokens: list[dict], model=None) -> Q:
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def nxt():
        tok = tokens[pos[0]]
        pos[0] += 1
        return tok

    def parse_expr() -> Q:
        groups = [parse_group()]
        while peek() and peek()['t'] == 'or':
            nxt()
            groups.append(parse_group())
        q = groups[0]
        for g in groups[1:]:
            q |= g
        return q

    def parse_group() -> Q:
        parts = []
        while peek() and peek()['t'] not in ('or', 'rp'):
            parts.append(parse_atom())
        if not parts:
            return Q()
        q = parts[0]
        for p in parts[1:]:
            q &= p
        return q

    def parse_atom() -> Q:
        if peek() and peek()['t'] == 'not':
            nxt()                   # consume !
            if not peek():
                return Q()          # bare ! at end of input → ignore
            return ~parse_atom()
        if peek() and peek()['t'] == 'lp':
            nxt()
            inner = parse_expr()
            if peek() and peek()['t'] == 'rp':
                nxt()
            return inner
        return make_filter(nxt())

    def make_filter(tok) -> Q:
        if tok is None:
            return Q()
        if tok['t'] == 'date_cmp':
            h = _DATE_CMP.get(tok['key'])
            if h:
                return h(tok['op'], tok['raw'])
            # Unrecognised key → free-text
            return _term_q(tok['key'] + tok['op'] + tok['raw'])
        if tok['t'] == 'cmp':
            h = _CMP.get(tok['key'])
            if h:
                return h(tok['op'], tok['num'])
            # Unrecognised key → free-text
            return _term_q(tok['key'] + tok['op'] + str(tok['num']))
        if tok['t'] == 'kv':
            # tag=<value> (not 'none') must use a pk-in subquery so that
            # multiple tag conditions don't collapse onto the same JOIN row.
            if tok['key'] == 'tag' and tok['val'] != 'none' and model is not None:
                return Q(pk__in=model.objects.filter(
                    tags__title__icontains=tok['val']
                ).values('pk'))
            h = _EQUALS.get(tok['key'])
            if h:
                return h(tok['val'])
            # Unrecognised key → free-text
            return _term_q(tok['key'] + '=' + tok['val'])
        # str token → free-text search
        return _term_q(tok.get('val', ''))

    return parse_expr()


def apply_query(qs, query_str: str):
    """Apply a search query string to an Expense queryset and return it filtered."""
    s = (query_str or '').strip()
    if not s:
        return qs
    return qs.filter(_compile(_tokenize(s.lower()), qs.model)).distinct()
