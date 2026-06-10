"""
Unit tests for the shared AI-call orchestration in budget/express_service.py:
merge_usage, record_ai_usage, and the retry/repair/notify control flow of
call_ai_for_json.

Django is not importable in the local venv without settings configured (as
with test_express_smart_create_blocks.py), so this mirrors the pure algorithms
-- the retry control flow is mirrored with the two AI calls and the admin
notifier injected as fakes, so it can be exercised without Django or network.
Run with: venv/bin/pytest tests/unit/test_ai_call_orchestration.py -v
"""
import json
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Mirror of extract_json_object (see test_express_json_extraction.py) ────

def extract_json_object(raw: str):
    cleaned = raw
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    idx = cleaned.find("{")
    if idx != -1:
        cleaned = cleaned[idx:]
    parsed, _end = json.JSONDecoder(strict=False).raw_decode(cleaned)
    return parsed


# ── Mirror of merge_usage / record_ai_usage ─────────────────────────────────

def merge_usage(*usages: dict) -> dict:
    keys = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens", "total_tokens")
    merged = {k: sum(u.get(k, 0) for u in usages) for k in keys}
    merged["cost_usd"] = round(sum(u.get("cost_usd", 0) for u in usages), 6)
    merged["cost_cents"] = round(sum(u.get("cost_cents", 0) for u in usages), 4)
    return merged


class FakeFeuser:
    def __init__(self, spent=None):
        self.ai_trial_budget_spent = spent
        self.save_calls = 0

    def save(self, update_fields=None):
        self.save_calls += 1


def record_ai_usage(feuser, is_trial: bool, usage: dict | None) -> None:
    if not (is_trial and usage):
        return
    feuser.ai_trial_budget_spent = (feuser.ai_trial_budget_spent or Decimal(0)) + Decimal(str(usage["cost_cents"]))
    feuser.save(update_fields=["ai_trial_budget_spent"])


# ── Mirror of call_ai_for_json's retry/merge/notify control flow ───────────

class RepairExhaustedError(Exception):
    def __init__(self, usage):
        self.usage = usage


def call_ai_for_json_sim(primary_call, repair_call, notify, feature="test_feature"):
    """
    Mirror of express_service.call_ai_for_json: the two AI calls and the
    admin-notify hook are injected as fakes (primary_call/repair_call each
    return (raw_text, usage) like _call_agent does) so the retry decision,
    usage merging, and notification behavior can be verified without Django
    or a real Anthropic call.
    """
    raw, usage = primary_call()
    try:
        return extract_json_object(raw), usage, raw
    except json.JSONDecodeError:
        pass

    repair_raw, repair_usage = repair_call()
    combined = merge_usage(usage, repair_usage)
    try:
        parsed = extract_json_object(repair_raw)
    except json.JSONDecodeError as exc:
        notify(feature, False)
        raise RepairExhaustedError(combined) from exc

    notify(feature, True)
    return parsed, combined, repair_raw


def _usage(cost_cents):
    return {
        "input_tokens": 10, "output_tokens": 5, "cache_write_tokens": 0,
        "cache_read_tokens": 0, "total_tokens": 15,
        "cost_usd": cost_cents / 100, "cost_cents": cost_cents,
    }


class TestMergeUsage:

    def test_sums_two_usages(self):
        merged = merge_usage(_usage(1.5), _usage(2.5))
        assert merged["cost_cents"] == 4.0
        assert merged["total_tokens"] == 30

    def test_single_usage_passthrough(self):
        merged = merge_usage(_usage(3.0))
        assert merged["cost_cents"] == 3.0
        assert merged["total_tokens"] == 15


class TestRecordAiUsage:

    def test_noop_when_not_trial(self):
        feuser = FakeFeuser(spent=Decimal("1.0"))
        record_ai_usage(feuser, False, _usage(5.0))
        assert feuser.ai_trial_budget_spent == Decimal("1.0")
        assert feuser.save_calls == 0

    def test_noop_when_usage_falsy(self):
        feuser = FakeFeuser(spent=Decimal("1.0"))
        record_ai_usage(feuser, True, None)
        record_ai_usage(feuser, True, {})
        assert feuser.ai_trial_budget_spent == Decimal("1.0")
        assert feuser.save_calls == 0

    def test_accumulates_onto_existing_spend(self):
        feuser = FakeFeuser(spent=Decimal("1.0"))
        record_ai_usage(feuser, True, _usage(2.5))
        assert feuser.ai_trial_budget_spent == Decimal("3.5")
        assert feuser.save_calls == 1

    def test_starts_from_zero_when_unset(self):
        feuser = FakeFeuser(spent=None)
        record_ai_usage(feuser, True, _usage(0.75))
        assert feuser.ai_trial_budget_spent == Decimal("0.75")


class TestCallAiForJsonRepairFallback:

    def test_repair_skipped_when_primary_parses(self):
        def primary():
            return '{"result": "good", "items": []}', _usage(1.0)

        def repair_should_not_run():
            raise AssertionError("repair should not be called when primary parses fine")

        notified = []
        parsed, usage, raw = call_ai_for_json_sim(
            primary, repair_should_not_run, lambda f, r: notified.append((f, r)),
        )
        assert parsed == {"result": "good", "items": []}
        assert usage["cost_cents"] == 1.0
        assert notified == []

    def test_repair_recovers_broken_primary_response(self):
        def primary():
            return "Sure! Here's your JSON, hope it helps somehow", _usage(1.0)

        def repair():
            return '{"result": "good", "items": [{"title": "Fixed"}]}', _usage(0.5)

        notified = []
        parsed, usage, raw = call_ai_for_json_sim(
            primary, repair, lambda f, r: notified.append((f, r)),
        )
        assert parsed["items"][0]["title"] == "Fixed"
        # Combined cost of both calls, not just the repair call.
        assert usage["cost_cents"] == 1.5
        assert notified == [("test_feature", True)]

    def test_repair_also_fails_raises_with_combined_usage(self):
        def primary():
            return "not json at all", _usage(1.0)

        def repair():
            return "still not json", _usage(0.5)

        notified = []
        with pytest.raises(RepairExhaustedError) as exc_info:
            call_ai_for_json_sim(primary, repair, lambda f, r: notified.append((f, r)))
        assert exc_info.value.usage["cost_cents"] == 1.5
        assert notified == [("test_feature", False)]
