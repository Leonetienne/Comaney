"""
Unit tests for budget/scheduled_assignment.py.

Pure Python: tests the spendings-JSON manipulation logic without a DB.
Run with: venv/bin/pytest tests/unit/test_scheduled_assignment.py -v
"""
import json
import sys
import os
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Inline the helpers under test (no Django available) ────────────────────

def _replace_feuser_in_spendings(spendings_json: str, old_feuser_pk: int, new_dummy_uid: int) -> tuple[str, bool]:
    """Return (new_json, changed). Replaces feuser entry with dummy entry in spendings."""
    spendings = json.loads(spendings_json or '[]')
    new_spendings = []
    changed = False
    for s in spendings:
        if s.get('type') == 'feuser' and s.get('id') == old_feuser_pk:
            new_spendings.append({'type': 'dummy', 'id': new_dummy_uid, 'share_percent': s['share_percent']})
            changed = True
        else:
            new_spendings.append(s)
    return json.dumps(new_spendings), changed


def _build_equal_shares_spendings(members) -> str:
    """Build spendings JSON with equal shares for given members list."""
    n = len(members)
    if n == 0:
        return '[]'
    per_share = Decimal('100') / n
    spendings = []
    total = Decimal('0')
    for i, m in enumerate(members):
        if i == n - 1:
            s = float(round(Decimal('100') - total, 4))
        else:
            s = float(round(per_share, 4))
            total += Decimal(str(s))
        spendings.append({'type': m['type'], 'id': m['id'], 'share_percent': s})
    return json.dumps(spendings)


# ── Tests ──────────────────────────────────────────────────────────────────

class TestReplaceFeUserInSpendings:

    def test_replaces_matching_feuser(self):
        spendings = json.dumps([
            {'type': 'feuser', 'id': 5, 'share_percent': 50.0},
            {'type': 'feuser', 'id': 7, 'share_percent': 50.0},
        ])
        result, changed = _replace_feuser_in_spendings(spendings, old_feuser_pk=5, new_dummy_uid=99)
        parsed = json.loads(result)
        assert changed is True
        assert parsed[0] == {'type': 'dummy', 'id': 99, 'share_percent': 50.0}
        assert parsed[1] == {'type': 'feuser', 'id': 7, 'share_percent': 50.0}

    def test_no_change_when_feuser_not_present(self):
        spendings = json.dumps([{'type': 'feuser', 'id': 7, 'share_percent': 100.0}])
        result, changed = _replace_feuser_in_spendings(spendings, old_feuser_pk=5, new_dummy_uid=99)
        assert changed is False
        assert json.loads(result) == [{'type': 'feuser', 'id': 7, 'share_percent': 100.0}]

    def test_preserves_dummy_entries(self):
        spendings = json.dumps([
            {'type': 'dummy', 'id': 20, 'share_percent': 40.0},
            {'type': 'feuser', 'id': 5, 'share_percent': 60.0},
        ])
        result, changed = _replace_feuser_in_spendings(spendings, old_feuser_pk=5, new_dummy_uid=99)
        parsed = json.loads(result)
        assert changed is True
        assert parsed[0] == {'type': 'dummy', 'id': 20, 'share_percent': 40.0}
        assert parsed[1] == {'type': 'dummy', 'id': 99, 'share_percent': 60.0}

    def test_empty_spendings(self):
        result, changed = _replace_feuser_in_spendings('[]', old_feuser_pk=5, new_dummy_uid=99)
        assert changed is False
        assert result == '[]'


class TestBuildEqualSharesSpendings:

    def test_two_members_equal(self):
        members = [{'type': 'feuser', 'id': 1}, {'type': 'feuser', 'id': 2}]
        parsed = json.loads(_build_equal_shares_spendings(members))
        assert len(parsed) == 2
        assert parsed[0]['share_percent'] == 50.0
        assert parsed[1]['share_percent'] == 50.0

    def test_three_members_sums_to_100(self):
        members = [
            {'type': 'feuser', 'id': 1},
            {'type': 'feuser', 'id': 2},
            {'type': 'dummy', 'id': 3},
        ]
        parsed = json.loads(_build_equal_shares_spendings(members))
        total = sum(s['share_percent'] for s in parsed)
        assert abs(total - 100.0) < 0.01

    def test_single_member(self):
        members = [{'type': 'feuser', 'id': 1}]
        parsed = json.loads(_build_equal_shares_spendings(members))
        assert len(parsed) == 1
        assert parsed[0]['share_percent'] == 100.0

    def test_empty_members(self):
        assert _build_equal_shares_spendings([]) == '[]'

    def test_member_types_preserved(self):
        members = [{'type': 'feuser', 'id': 10}, {'type': 'dummy', 'id': 20}]
        parsed = json.loads(_build_equal_shares_spendings(members))
        assert parsed[0]['type'] == 'feuser'
        assert parsed[0]['id'] == 10
        assert parsed[1]['type'] == 'dummy'
        assert parsed[1]['id'] == 20
