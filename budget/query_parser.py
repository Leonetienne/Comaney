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
    recurring=yes|no|true|false|1|0  (yes/true/1 = only recurring instances; no/false/0 = only non-recurring)
    shared=yes|no|true|false|1|0  (yes/true/1 = only buddy/shared expenses; no/false/0 = only non-shared)
    participant=me|<substring>  (me = feuser is owner or participant; substring matches owner or any participant)
    payer=me|<substring>  (me requires feuser context; substring matches owning user or offline buddy participant)
    value<N, value<=N, value>N, value>=N, value=N, value==N
    date<dd.mm.yyyy   date>=mm/dd/yyyy  date==yyyy-mm-dd  date>today
        dot delimiter → dd.mm.yyyy  |  slash delimiter → mm/dd/yyyy  |  hyphen → yyyy-mm-dd
        magic words: 'today', 'cur_week_start' (Monday), 'cur_week_end' (Sunday)
    cat=<substring>   cat=none  (expenses with no category visible to current user)
    tag=<substring>   tag=none  (expenses with no tag visible to current user)
    project=<yes|no|true|false|1|0|none|substring>
        yes/true/1 → has any project; no/false/0/none → has no project; substring → project name match
    payee=<none|substring>  none → no payee set
    <bare word or "quoted phrase">  →  free-text (title / payee / note / overlay note / buddy names / project names)
    !<atom>           →  NOT  (negates the next atom or parenthesised group)
"""

import re
from datetime import date as _date, timedelta as _timedelta
from decimal import Decimal, InvalidOperation
from django.db.models import Q


# Map the lowercased display names (as used in the UI) to internal DB values.
_TYPE_MAP: dict[str, str] = {
    "income":             "income",
    "expense":            "expense",
    "savings deposit":    "savings_dep",
    "savings withdrawal": "savings_wit",
    # Also accept internal codes directly.
    "savings_dep":        "savings_dep",
    "savings_wit":        "savings_wit",
}

_TOKEN_RE = re.compile(
    r'\|\|'                                                        # ||
    r'|!'                                                          # ! (NOT)
    r'|\('                                                         # (
    r'|\)'                                                         # )
    r'|(\w+)\s*(==|[<>]=?)\s*(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./]\d{1,2}[./]\d{4}|today|cur_week_start|cur_week_end)'  # g1-3: key op date
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
    """Parse magic words or explicit date formats: yyyy-mm-dd, dd.mm.yyyy, mm/dd/yyyy."""
    if raw == 'today':
        return _date.today()
    if raw == 'cur_week_start':
        today = _date.today()
        return today - _timedelta(days=today.weekday())   # Monday
    if raw == 'cur_week_end':
        today = _date.today()
        return today - _timedelta(days=today.weekday()) + _timedelta(days=6)  # Sunday
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


def _buddy_name_q(val: str) -> Q:
    """Q covering all buddy-related name fields (participants, project, project members)."""
    return (
        Q(buddy_spendings__participant_feuser__first_name__icontains=val)
        | Q(buddy_spendings__participant_feuser__last_name__icontains=val)
        | Q(buddy_spendings__participant_feuser__email__icontains=val)
        | Q(buddy_spendings__participant_dummy__display_name__icontains=val)
        | Q(project__name__icontains=val)
        | Q(project__members__feuser__first_name__icontains=val)
        | Q(project__members__feuser__last_name__icontains=val)
        | Q(project__members__feuser__email__icontains=val)
        | Q(project__members__dummy__display_name__icontains=val)
    )


def _shared_q(val: str, model=None) -> Q:
    """shared=<bool>: expense has (true) or lacks (false) BuddySpending rows."""
    if val in ('true', 'yes', '1'):
        if model is not None:
            return Q(pk__in=model.objects.filter(buddy_spendings__isnull=False).values('pk'))
        return Q(buddy_spendings__isnull=False)
    # false / no / 0
    return Q(buddy_spendings__isnull=True)


def _participant_q(val: str, model=None, feuser=None) -> Q:
    """participant=<me|substring>: person is owner, upfront payer, or BuddySpending participant."""
    if val == 'me' and feuser is not None:
        if model is not None:
            return Q(pk__in=model.objects.filter(
                Q(owning_feuser=feuser) | Q(buddy_spendings__participant_feuser=feuser)
            ).values('pk'))
        return Q(owning_feuser=feuser) | Q(buddy_spendings__participant_feuser=feuser)
    # Substring: owner name/email, upfront dummy payer, or BuddySpending participant name
    name_q = (
        Q(owning_feuser__first_name__icontains=val)
        | Q(owning_feuser__last_name__icontains=val)
        | Q(owning_feuser__email__icontains=val)
        | Q(upfront_payee_dummy__display_name__icontains=val)
        | Q(buddy_spendings__participant_feuser__first_name__icontains=val)
        | Q(buddy_spendings__participant_feuser__last_name__icontains=val)
        | Q(buddy_spendings__participant_feuser__email__icontains=val)
        | Q(buddy_spendings__participant_dummy__display_name__icontains=val)
    )
    if model is not None:
        return Q(pk__in=model.objects.filter(name_q).values('pk'))
    return name_q


def _payer_q(val: str, model=None, feuser=None) -> Q:
    """payer=<me|substring>: matches owning_feuser or dummy upfront payer (not participants)."""
    if val == 'me' and feuser is not None:
        return Q(owning_feuser=feuser)
    return (
        Q(owning_feuser__first_name__icontains=val)
        | Q(owning_feuser__last_name__icontains=val)
        | Q(owning_feuser__email__icontains=val)
        | Q(upfront_payee_dummy__display_name__icontains=val)
    )


def _project_q(val: str) -> Q:
    """project=<bool|none|substring>."""
    if val in ('false', 'no', '0', 'none'):
        return Q(project__isnull=True)
    if val in ('true', 'yes', '1'):
        return Q(project__isnull=False)
    return Q(project__name__icontains=val)


def _payee_q(val: str) -> Q:
    if val == 'none':
        return Q(payee='') | Q(payee__isnull=True)
    return Q(payee__icontains=val)


def _tag_q(val: str, model=None, feuser=None) -> Q:
    """tag=<none|substring> — also checks overlay tags for feuser."""
    if val == 'none':
        # No direct tags AND no overlay tags for feuser
        q = Q(tags__isnull=True)
        if feuser is not None and model is not None:
            q &= ~Q(pk__in=model.objects.filter(
                data_overlays__feuser=feuser,
                data_overlays__tags__isnull=False,
            ).values('pk'))
        return q
    # Substring: pk__in to avoid JOIN fanout on M2M tags
    if model is not None:
        q = Q(pk__in=model.objects.filter(tags__title__icontains=val).values('pk'))
        if feuser is not None:
            q |= Q(pk__in=model.objects.filter(
                data_overlays__feuser=feuser,
                data_overlays__tags__title__icontains=val,
            ).values('pk'))
        return q
    return Q(tags__title__icontains=val)


def _cat_q(val: str, model=None, feuser=None) -> Q:
    """cat=<none|substring> — also checks overlay category for feuser."""
    if val == 'none':
        q = Q(category__isnull=True)
        if feuser is not None and model is not None:
            q &= ~Q(pk__in=model.objects.filter(
                data_overlays__feuser=feuser,
                data_overlays__category__isnull=False,
            ).values('pk'))
        return q
    q = Q(category__title__icontains=val)
    if feuser is not None and model is not None:
        q |= Q(pk__in=model.objects.filter(
            data_overlays__feuser=feuser,
            data_overlays__category__title__icontains=val,
        ).values('pk'))
    return q


def _term_q(val: str, model=None, feuser=None) -> Q:
    q = Q(title__icontains=val) | Q(payee__icontains=val) | Q(note__icontains=val)
    if model is not None:
        q |= Q(pk__in=model.objects.filter(_buddy_name_q(val)).values('pk'))
        if feuser is not None:
            # Overlay note (null means "inherit expense note" — skip those)
            q |= Q(pk__in=model.objects.filter(
                data_overlays__feuser=feuser,
                data_overlays__note__icontains=val,
                data_overlays__note__isnull=False,
            ).values('pk'))
    return q


# ---------------------------------------------------------------------------
# Filter dispatch tables
# ---------------------------------------------------------------------------

_EQUALS: dict = {
    'type':        lambda v: _type_q(v),
    'settled':     lambda v: _bool_q('settled', v),
    'deactivated': lambda v: _bool_q('deactivated', v),
    'recurring':   lambda v: Q(source_scheduled__isnull=False) if v in ('true', 'yes', '1') else Q(source_scheduled__isnull=True),
    'value':       lambda v: _value_q('=', float(v)),
    'date':        lambda v: _date_q('=', v),
    'project':     lambda v: _project_q(v),
    'payee':       lambda v: _payee_q(v),
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

def _compile(tokens: list[dict], model=None, feuser=None) -> Q:
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
            return _term_q(tok['key'] + tok['op'] + tok['raw'], model, feuser)
        if tok['t'] == 'cmp':
            h = _CMP.get(tok['key'])
            if h:
                return h(tok['op'], tok['num'])
            return _term_q(tok['key'] + tok['op'] + str(tok['num']), model, feuser)
        if tok['t'] == 'kv':
            key = tok['key']
            val = tok['val']
            # Feuser-aware and special-cased filters
            if key == 'tag':
                return _tag_q(val, model, feuser)
            if key == 'cat':
                return _cat_q(val, model, feuser)
            if key == 'shared':
                return _shared_q(val, model)
            if key == 'participant':
                return _participant_q(val, model, feuser)
            if key == 'payer':
                return _payer_q(val, model, feuser)
            h = _EQUALS.get(key)
            if h:
                return h(val)
            # Unrecognised key → free-text
            return _term_q(key + '=' + val, model, feuser)
        # str token → free-text search (includes buddy/group name matching)
        return _term_q(tok.get('val', ''), model, feuser)

    return parse_expr()


def apply_query(qs, query_str: str, feuser=None):
    """Apply a search query string to an Expense queryset and return it filtered."""
    s = (query_str or '').strip()
    if not s:
        return qs
    return qs.filter(_compile(_tokenize(s.lower()), qs.model, feuser=feuser)).distinct()


def has_date_filter(query_str: str) -> bool:
    """Return True if the query contains any date comparison operator."""
    return bool(re.search(r'\bdate\s*(?:==|[<>]=?)', query_str or ''))
