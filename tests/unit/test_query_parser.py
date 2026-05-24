"""
Unit tests for the query parser tokeniser.

Only tests the pure-Python tokenisation layer — no Django, no DB.
Q-object construction and actual filtering are covered by E2E tests.
Run with: venv/bin/pytest tests/unit/test_query_parser.py -v
"""

import re

# ---------------------------------------------------------------------------
# Inline copy of the tokeniser — kept in sync with budget/query_parser.py.
# Django is not available in the local venv (runs in Docker), so we cannot
# import the module directly. Only the pure-Python tokenisation logic lives
# here; Q-object construction and actual filtering are covered by E2E tests.
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r'\|\|'
    r'|!'
    r'|\('
    r'|\)'
    r'|(\w+)\s*(==|[<>]=?)\s*(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./]\d{1,2}[./]\d{4}|today|cur_week_start|cur_week_end)'
    r'|(\w+)\s*(==|[<>]=?)\s*(\d+(?:\.\d+)?)'
    r'|(\w+)=(?:"([^"]*)"|([^\s()|"!]+))'
    r'|"([^"]*)"'
    r'|([^\s()|"!]+)'
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


class TestTokenizer:

    # ── Basic key=value ────────────────────────────────────────────────────

    def test_simple_kv(self):
        assert _tokenize('type=expense') == [{'t': 'kv', 'key': 'type', 'val': 'expense'}]

    def test_quoted_value(self):
        assert _tokenize('type="savings deposit"') == [{'t': 'kv', 'key': 'type', 'val': 'savings deposit'}]

    def test_bare_word(self):
        assert _tokenize('grocery') == [{'t': 'str', 'val': 'grocery'}]

    def test_quoted_phrase(self):
        assert _tokenize('"hello world"') == [{'t': 'str', 'val': 'hello world'}]

    # ── Operators ──────────────────────────────────────────────────────────

    def test_not_operator(self):
        tokens = _tokenize('!settled=yes')
        assert tokens[0] == {'t': 'not'}
        assert tokens[1] == {'t': 'kv', 'key': 'settled', 'val': 'yes'}

    def test_or_operator(self):
        tokens = _tokenize('a || b')
        types = [t['t'] for t in tokens]
        assert 'or' in types

    def test_parens(self):
        tokens = _tokenize('(type=expense)')
        types = [t['t'] for t in tokens]
        assert 'lp' in types
        assert 'rp' in types

    # ── Numeric and date comparisons ──────────────────────────────────────

    def test_cmp_gt(self):
        tokens = _tokenize('value>100')
        assert tokens[0] == {'t': 'cmp', 'key': 'value', 'op': '>', 'num': 100.0}

    def test_cmp_lte(self):
        tokens = _tokenize('value<=50.5')
        assert tokens[0] == {'t': 'cmp', 'key': 'value', 'op': '<=', 'num': 50.5}

    def test_date_cmp_iso(self):
        tokens = _tokenize('date>=2024-01-15')
        t = tokens[0]
        assert t['t'] == 'date_cmp'
        assert t['key'] == 'date'
        assert t['op'] == '>='
        assert t['raw'] == '2024-01-15'

    def test_date_cmp_magic_today(self):
        tokens = _tokenize('date>today')
        assert tokens[0]['raw'] == 'today'

    # ── New filters introduced by this feature ────────────────────────────

    def test_shared_true(self):
        assert _tokenize('shared=true') == [{'t': 'kv', 'key': 'shared', 'val': 'true'}]

    def test_shared_false(self):
        assert _tokenize('shared=false') == [{'t': 'kv', 'key': 'shared', 'val': 'false'}]

    def test_participant_me(self):
        assert _tokenize('participant=me') == [{'t': 'kv', 'key': 'participant', 'val': 'me'}]

    def test_participant_name(self):
        assert _tokenize('participant=alice') == [{'t': 'kv', 'key': 'participant', 'val': 'alice'}]

    def test_payer_me(self):
        assert _tokenize('payer=me') == [{'t': 'kv', 'key': 'payer', 'val': 'me'}]

    def test_payer_name(self):
        assert _tokenize('payer=john') == [{'t': 'kv', 'key': 'payer', 'val': 'john'}]

    def test_project_true(self):
        assert _tokenize('project=true') == [{'t': 'kv', 'key': 'project', 'val': 'true'}]

    def test_project_false(self):
        assert _tokenize('project=false') == [{'t': 'kv', 'key': 'project', 'val': 'false'}]

    def test_project_none(self):
        assert _tokenize('project=none') == [{'t': 'kv', 'key': 'project', 'val': 'none'}]

    def test_project_name(self):
        assert _tokenize('project=vacation') == [{'t': 'kv', 'key': 'project', 'val': 'vacation'}]

    def test_payee_none(self):
        assert _tokenize('payee=none') == [{'t': 'kv', 'key': 'payee', 'val': 'none'}]

    def test_payee_name(self):
        assert _tokenize('payee=amazon') == [{'t': 'kv', 'key': 'payee', 'val': 'amazon'}]

    # ── buddy= is no longer a recognised filter (falls to free-text) ──────

    def test_buddy_tokenises_as_kv(self):
        # Still tokenised as kv — the dispatcher treats it as free-text
        tokens = _tokenize('buddy=alice')
        assert tokens == [{'t': 'kv', 'key': 'buddy', 'val': 'alice'}]

    # ── Multi-token sequences ──────────────────────────────────────────────

    def test_multiple_filters_and(self):
        tokens = _tokenize('type=expense cat=food')
        keys = [t.get('key') for t in tokens if t['t'] == 'kv']
        assert keys == ['type', 'cat']

    def test_complex_expression(self):
        tokens = _tokenize('(shared=true payer=me) || project=none')
        types = [t['t'] for t in tokens]
        assert 'lp' in types
        assert 'or' in types
        assert 'rp' in types


# ---------------------------------------------------------------------------
# Inline copy of has_date_filter from budget/query_parser.py
# ---------------------------------------------------------------------------

def _has_date_filter(query_str: str) -> bool:
    import re
    return bool(re.search(r'\bdate\s*(?:==|[<>]=?)', query_str or ''))


class TestHasDateFilter:

    def test_date_gte(self):
        assert _has_date_filter('date>=2024-01-01') is True

    def test_date_gt(self):
        assert _has_date_filter('date>2024-06-15') is True

    def test_date_lte(self):
        assert _has_date_filter('date<=2024-12-31') is True

    def test_date_lt(self):
        assert _has_date_filter('date<today') is True

    def test_date_eq(self):
        assert _has_date_filter('date==2025-01-01') is True

    def test_no_date_filter(self):
        assert _has_date_filter('type=expense cat=food') is False

    def test_empty_string(self):
        assert _has_date_filter('') is False

    def test_none(self):
        assert _has_date_filter(None) is False

    def test_date_in_free_text(self):
        # "date" as a free-text word without a comparison operator is not a filter
        assert _has_date_filter('date') is False

    def test_mixed_with_other_filters(self):
        assert _has_date_filter('type=expense date>=2024-01-01') is True

    def test_combined_date_range(self):
        assert _has_date_filter('date>=2024-01-01 date<=2024-12-31') is True
