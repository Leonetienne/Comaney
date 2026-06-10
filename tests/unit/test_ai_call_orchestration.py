"""
Unit tests for the shared AI-call orchestration in budget/ai_service.py:
_merge_usage, _record_ai_usage (real imports -- see their docstring), and a
mirror of AIService._call_and_repair's retry/merge/notify control flow.

budget.ai_service has no module-level Django/DB imports, so _merge_usage and
_record_ai_usage are imported and exercised directly. AIService._call_and_repair
itself calls AIService._call, which does `import anthropic` and touches
django.conf.settings (via AIService.__init__/trial_state_for) -- neither
anthropic nor a configured settings module is available in this local venv,
so that one retry/merge/notify control flow is still mirrored here with the
two AI calls and the admin notifier injected as fakes.
Run with: venv/bin/pytest tests/unit/test_ai_call_orchestration.py -v
"""
import json
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from budget.ai_service import _extract_json_object as extract_json_object
from budget.ai_service import _merge_usage as merge_usage
from budget.ai_service import _record_ai_usage as record_ai_usage


class FakeFeuser:
    def __init__(self, spent=None):
        self.ai_trial_budget_spent = spent
        self.save_calls = 0

    def save(self, update_fields=None):
        self.save_calls += 1


# ── Mirror of AIService._call_and_repair's retry/merge/notify control flow ─

class RepairExhaustedError(Exception):
    def __init__(self, usage):
        self.usage = usage


def call_and_repair_sim(primary_call, repair_call, notify, feature="test_feature"):
    """
    Mirror of AIService._call_and_repair: the two AI calls and the
    admin-notify hook are injected as fakes (primary_call/repair_call each
    return (raw_text, usage) like AIService._call does) so the retry decision,
    usage merging, and notification behavior can be verified without Django,
    anthropic, or a real Anthropic call.
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


class TestCallAndRepairFallback:

    def test_repair_skipped_when_primary_parses(self):
        def primary():
            return '{"result": "good", "items": []}', _usage(1.0)

        def repair_should_not_run():
            raise AssertionError("repair should not be called when primary parses fine")

        notified = []
        parsed, usage, raw = call_and_repair_sim(
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
        parsed, usage, raw = call_and_repair_sim(
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
            call_and_repair_sim(primary, repair, lambda f, r: notified.append((f, r)))
        assert exc_info.value.usage["cost_cents"] == 1.5
        assert notified == [("test_feature", False)]
