"""
Unit tests for the AI project-participation override sanitizer in
budget/express_service.py::_sanitize_project_participants.

Django is not importable in the local venv, so (as with
test_express_project_type_coercion.py) this mirrors the pure algorithm.
Run with: venv/bin/pytest tests/unit/test_express_project_participants.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Mirror of _sanitize_project_participants (no Django needed) ─────────────

def sanitize(raw_participants, project_uid):
    if project_uid is None or not isinstance(raw_participants, list):
        return []
    cleaned = []
    for rp in raw_participants:
        if not isinstance(rp, dict):
            continue
        name = str(rp.get("name", "")).strip()
        if not name:
            continue
        included = rp.get("included", True)
        if not isinstance(included, bool):
            included = True
        entry = {"name": name[:255], "included": included}
        share = rp.get("share_percent")
        if share is not None:
            try:
                share = float(share)
            except (TypeError, ValueError):
                share = None
            if share is not None:
                entry["share_percent"] = max(0.0, min(100.0, share))
        cleaned.append(entry)
    return cleaned


class TestSanitizeProjectParticipants:

    def test_no_project_returns_empty(self):
        assert sanitize([{"name": "Robbie", "included": False}], None) == []

    def test_non_list_returns_empty(self):
        assert sanitize({"name": "Robbie"}, 7) == []
        assert sanitize(None, 7) == []

    def test_excluded_member(self):
        # "Robbie does not participate"
        assert sanitize([{"name": "Robbie", "included": False}], 7) == [
            {"name": "Robbie", "included": False}
        ]

    def test_pinned_zero_share(self):
        # "Robbie is on us, set him to 0%"
        assert sanitize(
            [{"name": "Robbie", "included": True, "share_percent": 0}], 7
        ) == [{"name": "Robbie", "included": True, "share_percent": 0.0}]

    def test_included_defaults_to_true(self):
        out = sanitize([{"name": "Alice", "share_percent": 25}], 7)
        assert out == [{"name": "Alice", "included": True, "share_percent": 25.0}]

    def test_share_clamped_to_range(self):
        assert sanitize([{"name": "A", "share_percent": 250}], 7)[0]["share_percent"] == 100.0
        assert sanitize([{"name": "B", "share_percent": -5}], 7)[0]["share_percent"] == 0.0

    def test_invalid_share_dropped_but_entry_kept(self):
        out = sanitize([{"name": "A", "share_percent": "notanumber"}], 7)
        assert out == [{"name": "A", "included": True}]

    def test_null_share_means_equal_split(self):
        # share_percent null -> no explicit share pinned (equal-split member)
        out = sanitize([{"name": "A", "included": True, "share_percent": None}], 7)
        assert out == [{"name": "A", "included": True}]

    def test_non_bool_included_coerced_true(self):
        out = sanitize([{"name": "A", "included": "yes"}], 7)
        assert out == [{"name": "A", "included": True}]

    def test_blank_and_non_dict_entries_skipped(self):
        out = sanitize(
            ["notadict", {"name": "  "}, {"name": "Real", "included": False}], 7
        )
        assert out == [{"name": "Real", "included": False}]


# ── Mirror of _sanitize_project_payer (no Django needed) ───────────────────

def sanitize_payer(raw_payer, project_uid):
    if project_uid is None or not isinstance(raw_payer, str):
        return None
    payer = raw_payer.strip()
    return payer[:255] if payer else None


class TestSanitizeProjectPayer:

    def test_no_project_returns_none(self):
        assert sanitize_payer("Volker Sauerbier", None) is None

    def test_non_string_returns_none(self):
        assert sanitize_payer({"name": "Volker"}, 7) is None
        assert sanitize_payer(None, 7) is None

    def test_blank_returns_none(self):
        assert sanitize_payer("   ", 7) is None

    def test_named_payer_kept_and_trimmed(self):
        assert sanitize_payer("  Volker Sauerbier  ", 7) == "Volker Sauerbier"

    def test_long_name_truncated(self):
        assert len(sanitize_payer("x" * 400, 7)) == 255


# ── Mirror of _sanitize_direct_buddy (no Django needed) ────────────────────

def sanitize_buddy(raw_name, raw_payer, raw_share, project_uid):
    if project_uid is not None or not isinstance(raw_name, str) or not raw_name.strip():
        return None, None, None
    name = raw_name.strip()[:255]
    payer = raw_payer.strip()[:255] if isinstance(raw_payer, str) and raw_payer.strip() else None
    share = None
    if raw_share is not None:
        try:
            share = max(0.0, min(100.0, float(raw_share)))
        except (TypeError, ValueError):
            share = None
    return name, payer, share


class TestSanitizeDirectBuddy:

    def test_dropped_when_project_set(self):
        # Direct buddy and project are mutually exclusive.
        assert sanitize_buddy("Volker", "Volker", 50, 7) == (None, None, None)

    def test_none_name_is_personal(self):
        assert sanitize_buddy(None, None, None, None) == (None, None, None)
        assert sanitize_buddy("   ", None, None, None) == (None, None, None)

    def test_name_only_equal_split(self):
        assert sanitize_buddy("Volker Sauerbier", None, None, None) == \
            ("Volker Sauerbier", None, None)

    def test_buddy_paid(self):
        assert sanitize_buddy("Volker", "Volker", None, None) == ("Volker", "Volker", None)

    def test_share_clamped(self):
        assert sanitize_buddy("A", None, 250, None) == ("A", None, 100.0)
        assert sanitize_buddy("B", None, -5, None) == ("B", None, 0.0)

    def test_invalid_share_dropped(self):
        assert sanitize_buddy("A", None, "nope", None) == ("A", None, None)

    def test_names_trimmed(self):
        assert sanitize_buddy("  Volker  ", "  me  ", 25, None) == ("Volker", "me", 25.0)
