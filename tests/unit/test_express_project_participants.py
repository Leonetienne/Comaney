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


# ── Mirror of _sanitize_project_participants + _normalize_participant_shares
# (no Django needed) ─────────────────────────────────────────────────────────

def normalize(cleaned, project_uid, member_count):
    mentioned = {e["idx"] for e in cleaned}
    included_idxs = {e["idx"] for e in cleaned if e["included"]} | (set(range(member_count)) - mentioned)
    pinned = [e for e in cleaned if e["included"] and "share_percent" in e]

    if len(included_idxs) == 1:
        only_idx = next(iter(included_idxs))
        for e in pinned:
            if e["idx"] == only_idx:
                e["share_percent"] = 100.0
        return cleaned

    if not pinned:
        return cleaned

    total = sum(e["share_percent"] for e in pinned)
    if total <= 0:
        return cleaned

    full_coverage = {e["idx"] for e in pinned} == included_idxs
    if total > 100 or (full_coverage and total < 100):
        scale = 100.0 / total
        for e in pinned:
            e["share_percent"] = e["share_percent"] * scale
    return cleaned


def sanitize(raw_participants, project_uid, member_count):
    if project_uid is None or not isinstance(raw_participants, list):
        return []
    cleaned = []
    for rp in raw_participants:
        if not isinstance(rp, dict):
            continue
        idx = rp.get("idx")
        if not isinstance(idx, int) or isinstance(idx, bool) or not (0 <= idx < member_count):
            continue
        included = rp.get("included", True)
        if not isinstance(included, bool):
            included = True
        entry = {"idx": idx, "included": included}
        share = rp.get("share_percent")
        if share is not None:
            try:
                share = float(share)
            except (TypeError, ValueError):
                share = None
            if share is not None:
                entry["share_percent"] = max(0.0, min(100.0, share))
        cleaned.append(entry)
    return normalize(cleaned, project_uid, member_count)


class TestSanitizeProjectParticipants:

    def test_no_project_returns_empty(self):
        assert sanitize([{"idx": 0, "included": False}], None, 3) == []

    def test_non_list_returns_empty(self):
        assert sanitize({"idx": 0}, 7, 3) == []
        assert sanitize(None, 7, 3) == []

    def test_excluded_member(self):
        # "Robbie (idx 0) does not participate"
        assert sanitize([{"idx": 0, "included": False}], 7, 3) == [
            {"idx": 0, "included": False}
        ]

    def test_pinned_zero_share(self):
        # "Robbie (idx 0) is on us, set him to 0%"
        assert sanitize(
            [{"idx": 0, "included": True, "share_percent": 0}], 7, 3
        ) == [{"idx": 0, "included": True, "share_percent": 0.0}]

    def test_included_defaults_to_true(self):
        out = sanitize([{"idx": 1, "share_percent": 25}], 7, 3)
        assert out == [{"idx": 1, "included": True, "share_percent": 25.0}]

    def test_share_clamped_to_range(self):
        assert sanitize([{"idx": 0, "share_percent": 250}], 7, 3)[0]["share_percent"] == 100.0
        assert sanitize([{"idx": 0, "share_percent": -5}], 7, 3)[0]["share_percent"] == 0.0

    def test_invalid_share_dropped_but_entry_kept(self):
        out = sanitize([{"idx": 0, "share_percent": "notanumber"}], 7, 3)
        assert out == [{"idx": 0, "included": True}]

    def test_null_share_means_equal_split(self):
        # share_percent null -> no explicit share pinned (equal-split member)
        out = sanitize([{"idx": 0, "included": True, "share_percent": None}], 7, 3)
        assert out == [{"idx": 0, "included": True}]

    def test_non_bool_included_coerced_true(self):
        out = sanitize([{"idx": 0, "included": "yes"}], 7, 3)
        assert out == [{"idx": 0, "included": True}]

    def test_blank_and_non_dict_entries_skipped(self):
        out = sanitize(
            ["notadict", {"included": False}, {"idx": 2, "included": False}], 7, 3
        )
        assert out == [{"idx": 2, "included": False}]

    def test_out_of_range_idx_dropped(self):
        assert sanitize([{"idx": 5, "included": False}], 7, 3) == []
        assert sanitize([{"idx": -1, "included": False}], 7, 3) == []

    def test_non_int_idx_dropped(self):
        assert sanitize([{"idx": "0", "included": False}], 7, 3) == []
        assert sanitize([{"idx": True, "included": False}], 7, 3) == []
        assert sanitize([{"idx": 1.5, "included": False}], 7, 3) == []

    def test_single_remaining_participant_forced_to_100(self):
        # Two members total; one excluded, the other pinned to something else.
        # The lone remaining participant must end up at 100%, not the pinned value.
        out = sanitize(
            [{"idx": 0, "included": False}, {"idx": 1, "included": True, "share_percent": 40}],
            7, 2,
        )
        assert out == [
            {"idx": 0, "included": False},
            {"idx": 1, "included": True, "share_percent": 100.0},
        ]

    def test_partial_pinned_shares_under_100_left_untouched(self):
        # 3 members; only one pinned to 30%. The other two (unlisted) absorb
        # the remaining 70% client-side -- no scaling needed server-side.
        out = sanitize([{"idx": 0, "included": True, "share_percent": 30}], 7, 3)
        assert out == [{"idx": 0, "included": True, "share_percent": 30.0}]

    def test_partial_pinned_shares_over_100_scaled_down(self):
        # 3 members; two pinned shares sum to 120 among themselves, which is
        # never valid regardless of any unlisted member -- scale proportionally.
        out = sanitize(
            [
                {"idx": 0, "included": True, "share_percent": 70},
                {"idx": 1, "included": True, "share_percent": 50},
            ],
            7, 3,
        )
        assert out[0]["share_percent"] == 58.333333333333336
        assert out[1]["share_percent"] == 41.66666666666667

    def test_full_coverage_shares_scaled_to_100(self):
        # Every member pinned explicitly (no unlisted member to absorb slack):
        # both over- and under-100 sums must be scaled to exactly 100.
        over = sanitize(
            [
                {"idx": 0, "included": True, "share_percent": 60},
                {"idx": 1, "included": True, "share_percent": 60},
            ],
            7, 2,
        )
        assert abs(sum(e["share_percent"] for e in over) - 100) < 1e-9

        under = sanitize(
            [
                {"idx": 0, "included": True, "share_percent": 20},
                {"idx": 1, "included": True, "share_percent": 20},
            ],
            7, 2,
        )
        assert abs(sum(e["share_percent"] for e in under) - 100) < 1e-9
        assert under[0]["share_percent"] == 50.0
        assert under[1]["share_percent"] == 50.0


# ── Mirror of _sanitize_project_payer (no Django needed) ───────────────────

def sanitize_payer(raw_payer, project_uid, member_count):
    if project_uid is None:
        return None
    if not isinstance(raw_payer, int) or isinstance(raw_payer, bool):
        return None
    if not (0 <= raw_payer < member_count):
        return None
    return raw_payer


class TestSanitizeProjectPayer:

    def test_no_project_returns_none(self):
        assert sanitize_payer(1, None, 3) is None

    def test_non_int_returns_none(self):
        assert sanitize_payer("Volker", 7, 3) is None
        assert sanitize_payer(None, 7, 3) is None
        assert sanitize_payer(1.5, 7, 3) is None

    def test_bool_returns_none(self):
        assert sanitize_payer(True, 7, 3) is None

    def test_valid_idx_kept(self):
        assert sanitize_payer(1, 7, 3) == 1

    def test_out_of_range_idx_returns_none(self):
        assert sanitize_payer(3, 7, 3) is None
        assert sanitize_payer(-1, 7, 3) is None


# ── Mirror of _sanitize_direct_buddy (no Django needed) ────────────────────

def sanitize_buddy(raw_idx, raw_paid, raw_share, project_uid, buddy_count):
    if project_uid is not None or not isinstance(raw_idx, int) or isinstance(raw_idx, bool):
        return None, False, None
    if not (0 <= raw_idx < buddy_count):
        return None, False, None
    paid = raw_paid is True
    share = None
    if raw_share is not None:
        try:
            share = max(0.0, min(100.0, float(raw_share)))
        except (TypeError, ValueError):
            share = None
    return raw_idx, paid, share


class TestSanitizeDirectBuddy:

    def test_dropped_when_project_set(self):
        # Direct buddy and project are mutually exclusive.
        assert sanitize_buddy(0, True, 50, 7, 3) == (None, False, None)

    def test_none_idx_is_personal(self):
        assert sanitize_buddy(None, None, None, None, 3) == (None, False, None)

    def test_out_of_range_idx_dropped(self):
        assert sanitize_buddy(5, True, None, None, 3) == (None, False, None)
        assert sanitize_buddy(-1, True, None, None, 3) == (None, False, None)

    def test_idx_only_equal_split(self):
        assert sanitize_buddy(0, None, None, None, 3) == (0, False, None)

    def test_buddy_paid(self):
        assert sanitize_buddy(0, True, None, None, 3) == (0, True, None)

    def test_non_bool_paid_treated_as_false(self):
        assert sanitize_buddy(0, "yes", None, None, 3) == (0, False, None)

    def test_share_clamped(self):
        assert sanitize_buddy(0, None, 250, None, 3) == (0, False, 100.0)
        assert sanitize_buddy(0, None, -5, None, 3) == (0, False, 0.0)

    def test_invalid_share_dropped(self):
        assert sanitize_buddy(0, None, "nope", None, 3) == (0, False, None)
