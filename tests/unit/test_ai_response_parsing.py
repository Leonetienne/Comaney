"""Response parsing, refusal handling and per-model billing in budget/ai_service.py.
Run with: venv/bin/pytest tests/unit/test_ai_response_parsing.py -v"""
import os
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from budget.ai_service import DEFAULT_EFFORT, EFFORT_CHOICES, AIRefusalError, resolve_effort
from budget.ai_service import _parse_response as parse_response
from budget.ai_service import _usage_from_response as usage_from_response


def _usage(input_tokens=0, output_tokens=0, cache_write=0, cache_read=0, iterations=None):
    return NS(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read,
        iterations=iterations,
    )


def _iteration(type_, model, input_tokens=0, output_tokens=0, cache_write=0, cache_read=0):
    return NS(
        type=type_, model=model, input_tokens=input_tokens, output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read,
    )


def _response(content, usage, stop_reason="end_turn", category=None, model="claude-sonnet-5-5"):
    stop_details = NS(type="refusal", category=category) if stop_reason == "refusal" else None
    return NS(model=model, content=content, usage=usage, stop_reason=stop_reason, stop_details=stop_details)


def _text(text):
    return NS(type="text", text=text)



class TestTextExtraction:

    def test_plain_text_response(self):
        raw, _usage_dict = parse_response(_response([_text('  {"a": 1}  ')], _usage(10, 5)))
        assert raw == '{"a": 1}'

    def test_skips_leading_thinking_blocks(self):
        content = [NS(type="thinking", thinking=""), NS(type="thinking", thinking=""), _text('{"ok": true}')]
        raw, _ = parse_response(_response(content, _usage(10, 5)))
        assert raw == '{"ok": true}'

    def test_skips_leading_fallback_marker(self):
        content = [
            NS(type="fallback", from_=NS(model="claude-sonnet-5-5"), to=NS(model="claude-sonnet-5")),
            _text('{"ok": true}'),
        ]
        raw, _ = parse_response(_response(content, _usage(10, 5), model="claude-sonnet-5"))
        assert raw == '{"ok": true}'

    def test_takes_the_first_text_block_only(self):
        raw, _ = parse_response(_response([_text("first"), _text("second")], _usage(1, 1)))
        assert raw == "first"

    def test_no_text_block_is_still_the_empty_response_error(self):
        with pytest.raises(ValueError, match="empty response"):
            parse_response(_response([NS(type="thinking", thinking="")], _usage(10, 0)))



class TestRefusal:

    def test_refusal_raises_readable_refusal_error(self):
        resp = _response([], _usage(500, 0), stop_reason="refusal", category="bio")
        with pytest.raises(AIRefusalError) as excinfo:
            parse_response(resp)
        message = str(excinfo.value)
        assert "declined" in message
        assert "empty response" not in message
        assert excinfo.value.raw == ""

    def test_refusal_is_checked_before_reading_content(self):
        """Partial text from a mid-output refusal still raises."""
        resp = _response([_text('{"partial": ')], _usage(500, 40), stop_reason="refusal", category="cyber")
        with pytest.raises(AIRefusalError):
            parse_response(resp)

    def test_refusal_carries_usage_for_billing(self):
        resp = _response([], _usage(1_000_000, 0), stop_reason="refusal", category="frontier_llm")
        with pytest.raises(AIRefusalError) as excinfo:
            parse_response(resp)
        assert excinfo.value.usage["cost_usd"] == 2.00

    def test_null_category_is_handled(self):
        with pytest.raises(AIRefusalError):
            parse_response(_response([], _usage(10, 0), stop_reason="refusal", category=None))

    def test_envelope_fail_refusal_has_no_usage(self):
        """Envelope "fail" is billed before raising, so it carries no usage."""
        assert AIRefusalError("nope", "raw").usage is None



class TestBilling:

    def test_no_iterations_uses_top_level_usage_and_model(self):
        usage = usage_from_response(_response([_text("x")], _usage(1_000_000, 100_000, 0, 0)))
        assert usage["cost_usd"] == 3.00  # 2.00 input + 1.00 output
        assert usage["cost_cents"] == 300.0
        assert usage["input_tokens"] == 1_000_000
        assert usage["total_tokens"] == 1_100_000

    def test_cache_tokens_billed_at_cache_rates(self):
        usage = usage_from_response(_response([_text("x")], _usage(0, 0, cache_write=1_000_000, cache_read=1_000_000)))
        assert usage["cost_usd"] == 2.70  # 2.50 write + 0.20 read
        assert usage["cache_write_tokens"] == 1_000_000
        assert usage["cache_read_tokens"] == 1_000_000

    def test_cheap_cached_call_keeps_four_decimal_precision(self):
        usage = usage_from_response(_response([_text("x")], _usage(0, 3, cache_read=200)))
        assert usage["cost_cents"] == 0.007  # 3 * $10/M + 200 * $0.20/M = $0.00007
        assert round(usage["cost_cents"], 1) == 0.0

    def test_fallback_sums_every_attempt_at_its_own_model_rates(self):
        """Billing follows usage.iterations, top-level usage is the serving attempt only."""
        iterations = [
            _iteration("message", "claude-sonnet-5-5", input_tokens=1_000_000, output_tokens=50_000),
            _iteration("fallback_message", "claude-sonnet-5", input_tokens=1_000_000, output_tokens=100_000),
        ]
        resp = _response(
            [NS(type="fallback"), _text("ok")],
            _usage(1_000_000, 100_000, iterations=iterations),
            model="claude-sonnet-5",
        )
        usage = usage_from_response(resp)
        # 5.5 mid-output decline: 2.00 + 0.50; Sonnet 5 answer: 2.00 + 1.00
        assert usage["cost_usd"] == 5.50
        assert usage["input_tokens"] == 2_000_000
        assert usage["output_tokens"] == 150_000

    def test_attempt_without_reported_model_billed_at_default_rates(self):
        """Iteration without model (optional in anthropic 1.x) bills at Sonnet 5.5 rates."""
        iterations = [_iteration("message", None, input_tokens=1_000_000, output_tokens=0)]
        resp = _response([_text("ok")], _usage(1_000_000, 0, iterations=iterations))
        assert usage_from_response(resp)["cost_usd"] == 2.00

    def test_rescued_pre_output_decline_is_billed(self):
        """Rescued declined attempt reports no category, so it's billed."""
        iterations = [
            _iteration("message", "claude-sonnet-5-5", input_tokens=1_000_000, output_tokens=0),
            _iteration("fallback_message", "claude-sonnet-5", input_tokens=1_000_000, output_tokens=0),
        ]
        resp = _response([_text("ok")], _usage(1_000_000, 0, iterations=iterations), model="claude-sonnet-5")
        assert usage_from_response(resp)["cost_usd"] == 4.00

    @pytest.mark.parametrize("category", ["cyber", "general_harms", None])
    def test_final_pre_output_refusal_in_unbilled_category_costs_nothing(self, category):
        resp = _response([], _usage(1_000_000, 0), stop_reason="refusal", category=category)
        usage = usage_from_response(resp)
        assert usage["cost_usd"] == 0.0
        assert usage["total_tokens"] == 0

    @pytest.mark.parametrize("category", ["bio", "frontier_llm", "reasoning_extraction"])
    def test_final_pre_output_refusal_in_billed_category_is_billed(self, category):
        resp = _response([], _usage(1_000_000, 0), stop_reason="refusal", category=category)
        assert usage_from_response(resp)["cost_usd"] == 2.00

    def test_final_mid_output_refusal_is_always_billed(self):
        resp = _response([], _usage(1_000_000, 100_000), stop_reason="refusal", category="cyber")
        assert usage_from_response(resp)["cost_usd"] == 3.00

    def test_whole_chain_refused_skips_only_the_unbilled_final_attempt(self):
        iterations = [
            _iteration("message", "claude-sonnet-5-5", input_tokens=1_000_000, output_tokens=0),
            _iteration("fallback_message", "claude-sonnet-5", input_tokens=1_000_000, output_tokens=0),
        ]
        resp = _response(
            [], _usage(1_000_000, 0, iterations=iterations),
            stop_reason="refusal", category="cyber", model="claude-sonnet-5",
        )
        assert usage_from_response(resp)["cost_usd"] == 2.00




class TestResolveEffort:

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_unset_means_medium(self, value):
        assert resolve_effort(value) == ("medium", None)
        assert DEFAULT_EFFORT == "medium"

    @pytest.mark.parametrize("value", list(EFFORT_CHOICES))
    def test_every_documented_level_is_accepted(self, value):
        assert resolve_effort(value) == (value, None)

    def test_case_and_whitespace_are_tolerated(self):
        assert resolve_effort("  HIGH ") == ("high", None)

    @pytest.mark.parametrize("value", ["minimal", "none", "1", "med"])
    def test_invalid_value_returns_error_naming_the_env_var(self, value):
        effort, error = resolve_effort(value)
        assert effort == "medium"
        assert "AI_PROVIDER_CLAUDE_EFFORT" in error
        assert "low, medium, high, xhigh, max" in error
