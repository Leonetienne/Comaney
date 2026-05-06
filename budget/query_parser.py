"""
Expense search query parser.

Parses the same query language understood by the client-side JS filter and
translates it into Django Q objects so the backend can apply it to an
Expense queryset.

Grammar (mirrors JS):
    expr  = group ('||' group)*
    group = atom*
    atom  = '(' expr ')' | filter

Filters:
    type=income / type=expense / type="savings deposit" / …
    settled=yes|no|true|false|1|0
    value<N, value<=N, value>N, value>=N, value=N
    cat=<substring>
    tag=<substring>
    payee=<substring>
    <bare word or "quoted phrase">  →  free-text (title / payee / note)
"""

import re
from decimal import Decimal
from django.db.models import Q


# Map the lowercased display names (as used in the UI) to internal DB values.
_TYPE_MAP: dict[str, str] = {
    "income":            "income",
    "expense":           "expense",
    "savings deposit":   "savings_dep",
    "savings withdrawal":"savings_wit",
    "carry-over":        "carry_over",
    "carry over":        "carry_over",
    # Also accept internal codes directly.
    "savings_dep":       "savings_dep",
    "savings_wit":       "savings_wit",
    "carry_over":        "carry_over",
}

_TOKEN_RE = re.compile(
    r'\|\|'                                        # ||
    r'|\('                                          # (
    r'|\)'                                          # )
    r'|(\w+)\s*([<>]=?)\s*(\d+(?:\.\d+)?)'        # key op num  (cmp)
    r'|(\w+)=(?:"([^"]*)"|([^\s()|"]+))'           # key="v" or key=v  (kv)
    r'|"([^"]*)"'                                   # "quoted phrase"  (str)
    r'|([^\s()|"]+)'                                # bare word  (str)
)


def _tokenize(raw: str) -> list[dict]:
    out: list[dict] = []
    for m in _TOKEN_RE.finditer(raw):
        s = m.group(0)
        if s == '||':
            out.append({'t': 'or'})
        elif s == '(':
            out.append({'t': 'lp'})
        elif s == ')':
            out.append({'t': 'rp'})
        elif m.group(1):
            out.append({'t': 'cmp', 'key': m.group(1), 'op': m.group(2), 'num': float(m.group(3))})
        elif m.group(4):
            val = m.group(5) if m.group(5) is not None else (m.group(6) or '')
            out.append({'t': 'kv', 'key': m.group(4), 'val': val})
        elif m.group(7) is not None:
            out.append({'t': 'str', 'val': m.group(7)})
        else:
            out.append({'t': 'str', 'val': m.group(8) or ''})
    return out


def _type_q(val: str) -> Q:
    internal = _TYPE_MAP.get(val)
    return Q(type=internal) if internal else Q(type=val)


def _settled_q(val: str) -> Q:
    return Q(settled=val in ('true', 'yes', '1'))


def _value_q(op: str, num: float) -> Q:
    d = Decimal(str(num))
    lookup = {'<': 'lt', '<=': 'lte', '>': 'gt', '>=': 'gte', '=': 'exact'}.get(op, 'exact')
    return Q(**{f'value__{lookup}': d})


_EQUALS: dict = {
    'type':    lambda v: _type_q(v),
    'settled': lambda v: _settled_q(v),
    'value':   lambda v: _value_q('=', float(v)),
    'tag':     lambda v: Q(tags__title__icontains=v),
    'cat':     lambda v: Q(category__title__icontains=v),
    'payee':   lambda v: Q(payee__icontains=v),
}

_CMP: dict = {
    'value': lambda op, num: _value_q(op, num),
}


def _term_q(val: str) -> Q:
    return Q(title__icontains=val) | Q(payee__icontains=val) | Q(note__icontains=val)


def _compile(tokens: list[dict]) -> Q:
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
        if tok['t'] == 'cmp':
            h = _CMP.get(tok['key'])
            if h:
                return h(tok['op'], tok['num'])
        if tok['t'] == 'kv':
            h = _EQUALS.get(tok['key'])
            if h:
                return h(tok['val'])
        # Unrecognised token → fold into free-text search.
        if tok['t'] == 'str':
            term = tok['val']
        elif tok['t'] == 'cmp':
            term = tok['key'] + tok['op'] + str(tok['num'])
        else:
            term = tok['key'] + '=' + tok['val']
        return _term_q(term)

    return parse_expr()


def apply_query(qs, query_str: str):
    """Apply a search query string to an Expense queryset and return it filtered."""
    s = (query_str or '').strip()
    if not s:
        return qs
    return qs.filter(_compile(_tokenize(s.lower()))).distinct()
