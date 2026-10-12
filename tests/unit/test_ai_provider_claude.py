"""ai_providers/claude.py: request translation, response parsing, refusals,
per-model billing, price overrides and SDK exception mapping. The `anthropic`
SDK is not installed in the local venv; a stand-in module is injected.
Run with: venv/bin/pytest tests/unit/test_ai_provider_claude.py -v"""
from types import SimpleNamespace as NS

import pytest

from ai_providers import load_provider
from ai_providers.base import AIRequest, ImageInput, SystemPart
from ai_providers.claude import ClaudeProvider, compute_cost
from ai_providers.errors import (
    AIAuthenticationError,
    AIBillingError,
    AIError,
    AIRefusalError,
    AITransientError,
    ProviderConfigError,
)


def _provider(sdk=None, **fields):
    return ClaudeProvider({k: v for k, v in fields.items()}, sdk=sdk)


# ── response stand-ins ──────────────────────────────────────────────────────

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


# ── SDK stand-in ────────────────────────────────────────────────────────────

class _APIError(Exception):
    pass


class _APIStatusError(_APIError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class _AuthenticationError(_APIStatusError):
    pass


class _PermissionDeniedError(_APIStatusError):
    pass


class _RateLimitError(_APIStatusError):
    pass


class _InternalServerError(_APIStatusError):
    pass


class _APIConnectionError(_APIError):
    pass


class FakeSDK:
    """Mimics the parts of the `anthropic` module ClaudeProvider uses, and
    records every client construction and create() call."""
    AuthenticationError = _AuthenticationError
    PermissionDeniedError = _PermissionDeniedError
    RateLimitError = _RateLimitError
    InternalServerError = _InternalServerError
    APIConnectionError = _APIConnectionError
    APIStatusError = _APIStatusError

    def __init__(self, response=None, raises=None):
        self.response = response or _response([_text('{"ok": true}')], _usage(10, 5))
        self.raises = raises
        self.api_keys = []
        self.calls = []

    def Anthropic(self, api_key):
        self.api_keys.append(api_key)
        sdk = self

        def create(**kwargs):
            sdk.calls.append(kwargs)
            if sdk.raises:
                raise sdk.raises
            return sdk.response
        return NS(beta=NS(messages=NS(create=create)))


def _request(**overrides):
    values = {"feature": "test", "system": [SystemPart("sys")], "user_text": "hello", "max_tokens": 4096}
    values.update(overrides)
    return AIRequest(**values)


# ── request translation ─────────────────────────────────────────────────────

class TestMessageTranslation:

    def test_cacheable_parts_get_cache_control(self):
        system = ClaudeProvider.build_system(_request(system=[SystemPart("a"), SystemPart("b", cacheable=False)]))
        assert system == [
            {"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "b"},
        ]

    def test_text_only_is_a_plain_string(self):
        assert ClaudeProvider.build_messages(_request()) == [{"role": "user", "content": "hello"}]

    def test_images_come_before_the_text(self):
        messages = ClaudeProvider.build_messages(_request(images=[ImageInput("QUJD", "image/png")]))
        assert messages == [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
            {"type": "text", "text": "hello"},
        ]}]


class TestSend:

    def test_request_shape(self):
        sdk = FakeSDK()
        _provider(sdk, api_key="sk-shared").send(_request(), {})
        call = sdk.calls[0]
        assert call["model"] == "claude-sonnet-5-5"
        assert call["output_config"] == {"effort": "medium"}
        assert call["betas"] == ["server-side-fallback-2026-07-01"]
        assert call["fallbacks"] == "default"
        assert call["system"][0]["cache_control"] == {"type": "ephemeral"}

    def test_shared_access_uses_instance_key(self):
        sdk = FakeSDK()
        _provider(sdk, api_key="sk-shared").send(_request(), {})
        assert sdk.api_keys == ["sk-shared"]

    def test_user_config_key_wins(self):
        sdk = FakeSDK()
        _provider(sdk, api_key="sk-shared").send(_request(), {"api_key": "sk-own"})
        assert sdk.api_keys == ["sk-own"]

    def test_configured_model_and_effort(self):
        sdk = FakeSDK()
        _provider(sdk, model="claude-sonnet-5", effort="high").send(_request(), {})
        assert sdk.calls[0]["model"] == "claude-sonnet-5"
        assert sdk.calls[0]["output_config"] == {"effort": "high"}

    def test_max_tokens_capped_by_admin_option(self):
        sdk = FakeSDK()
        _provider(sdk, max_tokens="2000").send(_request(max_tokens=8192), {})
        assert sdk.calls[0]["max_tokens"] == 2000

    def test_feature_max_tokens_used_below_cap(self):
        sdk = FakeSDK()
        _provider(sdk).send(_request(max_tokens=4096), {})
        assert sdk.calls[0]["max_tokens"] == 4096

    def test_returns_text_cost_and_usage(self):
        sdk = FakeSDK(_response([_text(" {} ")], _usage(1_000_000, 0)))
        result = _provider(sdk).send(_request(), {})
        assert result.text == "{}"
        assert result.cost_cents == 200.0
        assert result.usage["input_tokens"] == 1_000_000
        assert result.usage["total_tokens"] == 1_000_000


# ── response parsing ────────────────────────────────────────────────────────

class TestTextExtraction:

    def _parse(self, response):
        return _provider().parse_response(response)

    def test_plain_text_response(self):
        assert self._parse(_response([_text('  {"a": 1}  ')], _usage(10, 5))).text == '{"a": 1}'

    def test_skips_leading_thinking_blocks(self):
        content = [NS(type="thinking", thinking=""), NS(type="thinking", thinking=""), _text('{"ok": true}')]
        assert self._parse(_response(content, _usage(10, 5))).text == '{"ok": true}'

    def test_skips_leading_fallback_marker(self):
        content = [
            NS(type="fallback", from_=NS(model="claude-sonnet-5-5"), to=NS(model="claude-sonnet-5")),
            _text('{"ok": true}'),
        ]
        assert self._parse(_response(content, _usage(10, 5), model="claude-sonnet-5")).text == '{"ok": true}'

    def test_takes_the_first_text_block_only(self):
        assert self._parse(_response([_text("first"), _text("second")], _usage(1, 1))).text == "first"

    def test_no_text_block_is_an_unexpected_error(self):
        with pytest.raises(AIError, match="Unexpected error: Claude returned an empty response"):
            self._parse(_response([NS(type="thinking", thinking="")], _usage(10, 0)))


class TestRefusal:

    def _parse(self, response):
        return _provider().parse_response(response)

    def test_refusal_raises_readable_refusal_error(self):
        with pytest.raises(AIRefusalError) as excinfo:
            self._parse(_response([], _usage(500, 0), stop_reason="refusal", category="bio"))
        assert "declined" in str(excinfo.value)
        assert "empty response" not in str(excinfo.value)
        assert excinfo.value.raw == ""

    def test_refusal_is_checked_before_reading_content(self):
        """Partial text from a mid-output refusal still raises."""
        with pytest.raises(AIRefusalError):
            self._parse(_response([_text('{"partial": ')], _usage(500, 40), stop_reason="refusal", category="cyber"))

    def test_refusal_carries_usage_for_billing(self):
        with pytest.raises(AIRefusalError) as excinfo:
            self._parse(_response([], _usage(1_000_000, 0), stop_reason="refusal", category="frontier_llm"))
        assert excinfo.value.usage["cost_usd"] == 2.00
        assert excinfo.value.usage["cost_cents"] == 200.0

    def test_null_category_is_handled(self):
        with pytest.raises(AIRefusalError):
            self._parse(_response([], _usage(10, 0), stop_reason="refusal", category=None))

    def test_refusal_through_send_is_not_reclassified(self):
        sdk = FakeSDK(_response([], _usage(10, 0), stop_reason="refusal", category="cyber"))
        with pytest.raises(AIRefusalError):
            _provider(sdk).send(_request(), {})

    def test_envelope_fail_refusal_has_no_usage(self):
        """Envelope "fail" is billed before raising, so it carries no usage."""
        assert AIRefusalError("nope", "raw").usage is None


# ── billing ─────────────────────────────────────────────────────────────────

class TestComputeCost:
    PRICES = (2.00, 10.00, 2.50, 0.20)

    def test_input_and_output_per_mtok(self):
        assert compute_cost(1_000_000, 0, 0, 0, self.PRICES) == 2.00
        assert compute_cost(0, 1_000_000, 0, 0, self.PRICES) == 10.00

    def test_cache_write_and_read_priced_independently(self):
        assert compute_cost(0, 0, 1_000_000, 0, self.PRICES) == 2.50
        assert compute_cost(0, 0, 0, 1_000_000, self.PRICES) == 0.20

    def test_zero_usage_is_zero_cost(self):
        assert compute_cost(0, 0, 0, 0, self.PRICES) == 0.0


class TestBilling:

    def _usage_of(self, response, **fields):
        return _provider(**fields).usage_from_response(response)

    def test_no_iterations_uses_top_level_usage_and_model(self):
        usage = self._usage_of(_response([_text("x")], _usage(1_000_000, 100_000)))
        assert usage["cost_usd"] == 3.00
        assert usage["cost_cents"] == 300.0
        assert usage["input_tokens"] == 1_000_000
        assert usage["total_tokens"] == 1_100_000

    def test_cache_tokens_billed_at_cache_rates(self):
        usage = self._usage_of(_response([_text("x")], _usage(0, 0, cache_write=1_000_000, cache_read=1_000_000)))
        assert usage["cost_usd"] == 2.70
        assert usage["cache_write_tokens"] == 1_000_000
        assert usage["cache_read_tokens"] == 1_000_000

    def test_cheap_cached_call_keeps_four_decimal_precision(self):
        """Would round to 0.0 at 1 decimal and escape trial-budget accounting."""
        usage = self._usage_of(_response([_text("x")], _usage(0, 3, cache_read=200)))
        assert usage["cost_cents"] == 0.007
        assert round(usage["cost_cents"], 1) == 0.0

    def test_fallback_sums_every_attempt_at_its_own_model_rates(self):
        iterations = [
            _iteration("message", "claude-sonnet-5-5", input_tokens=1_000_000, output_tokens=50_000),
            _iteration("fallback_message", "claude-sonnet-5", input_tokens=1_000_000, output_tokens=100_000),
        ]
        resp = _response(
            [NS(type="fallback"), _text("ok")],
            _usage(1_000_000, 100_000, iterations=iterations), model="claude-sonnet-5",
        )
        usage = self._usage_of(resp)
        assert usage["cost_usd"] == 5.50
        assert usage["input_tokens"] == 2_000_000
        assert usage["output_tokens"] == 150_000

    def test_attempt_without_reported_model_billed_at_configured_model(self):
        iterations = [_iteration("message", None, input_tokens=1_000_000)]
        resp = _response([_text("ok")], _usage(1_000_000, 0, iterations=iterations))
        assert self._usage_of(resp)["cost_usd"] == 2.00

    def test_unknown_reported_model_billed_at_configured_model(self):
        iterations = [_iteration("message", "claude-something-new", input_tokens=1_000_000)]
        resp = _response([_text("ok")], _usage(1_000_000, 0, iterations=iterations))
        assert self._usage_of(resp, price_input="7", price_output="9", model="claude-custom")["cost_usd"] == 7.00

    def test_rescued_pre_output_decline_is_billed(self):
        iterations = [
            _iteration("message", "claude-sonnet-5-5", input_tokens=1_000_000),
            _iteration("fallback_message", "claude-sonnet-5", input_tokens=1_000_000),
        ]
        resp = _response([_text("ok")], _usage(1_000_000, 0, iterations=iterations), model="claude-sonnet-5")
        assert self._usage_of(resp)["cost_usd"] == 4.00

    @pytest.mark.parametrize("category", ["cyber", "general_harms", None])
    def test_final_pre_output_refusal_in_unbilled_category_costs_nothing(self, category):
        usage = self._usage_of(_response([], _usage(1_000_000, 0), stop_reason="refusal", category=category))
        assert usage["cost_usd"] == 0.0
        assert usage["total_tokens"] == 0

    @pytest.mark.parametrize("category", ["bio", "frontier_llm", "reasoning_extraction"])
    def test_final_pre_output_refusal_in_billed_category_is_billed(self, category):
        resp = _response([], _usage(1_000_000, 0), stop_reason="refusal", category=category)
        assert self._usage_of(resp)["cost_usd"] == 2.00

    def test_final_mid_output_refusal_is_always_billed(self):
        resp = _response([], _usage(1_000_000, 100_000), stop_reason="refusal", category="cyber")
        assert self._usage_of(resp)["cost_usd"] == 3.00

    def test_whole_chain_refused_skips_only_the_unbilled_final_attempt(self):
        iterations = [
            _iteration("message", "claude-sonnet-5-5", input_tokens=1_000_000),
            _iteration("fallback_message", "claude-sonnet-5", input_tokens=1_000_000),
        ]
        resp = _response(
            [], _usage(1_000_000, 0, iterations=iterations),
            stop_reason="refusal", category="cyber", model="claude-sonnet-5",
        )
        assert self._usage_of(resp)["cost_usd"] == 2.00


class TestPrices:

    def test_known_models_from_table(self):
        provider = _provider()
        assert provider.model_prices("claude-sonnet-5-5") == (2.00, 10.00, 2.50, 0.20)
        assert provider.model_prices("claude-sonnet-5") == (2.00, 10.00, 2.50, 0.20)

    def test_override_prices_configured_model_with_cache_multipliers(self):
        provider = _provider(model="claude-custom", price_input="4", price_output="20")
        assert provider.model_prices("claude-custom") == (4.0, 20.0, 5.0, 0.4)

    def test_override_also_replaces_table_price_of_configured_model(self):
        provider = _provider(price_input="1", price_output="5")
        assert provider.model_prices("claude-sonnet-5-5")[:2] == (1.0, 5.0)
        # the fallback target keeps its own table price
        assert provider.model_prices("claude-sonnet-5") == (2.00, 10.00, 2.50, 0.20)

    def test_unknown_model_without_override_is_rejected(self):
        with pytest.raises(ProviderConfigError, match="No price is known for AI_PROVIDER_CLAUDE_MODEL='claude-custom'"):
            load_provider("claude", {"AI_PROVIDER_CLAUDE_MODEL": "claude-custom"})

    def test_unknown_model_with_override_loads(self):
        provider = load_provider("claude", {
            "AI_PROVIDER_CLAUDE_MODEL": "claude-custom",
            "AI_PROVIDER_CLAUDE_PRICE_INPUT": "3",
            "AI_PROVIDER_CLAUDE_PRICE_OUTPUT": "15",
        })
        assert provider.model_prices("claude-custom")[:2] == (3.0, 15.0)

    @pytest.mark.parametrize("field", ["PRICE_INPUT", "PRICE_OUTPUT"])
    def test_one_price_without_the_other_is_rejected(self, field):
        with pytest.raises(ProviderConfigError, match="Set both"):
            load_provider("claude", {f"AI_PROVIDER_CLAUDE_{field}": "3"})


# ── exception mapping ───────────────────────────────────────────────────────

class TestExceptionMapping:

    def _send_raising(self, exc):
        _provider(FakeSDK(raises=exc)).send(_request(), {})

    def test_authentication(self):
        with pytest.raises(AIAuthenticationError, match="Invalid API key"):
            self._send_raising(_AuthenticationError("bad key", 401))

    def test_permission_denied(self):
        with pytest.raises(AIAuthenticationError, match="does not have permission"):
            self._send_raising(_PermissionDeniedError("nope", 403))

    def test_rate_limit_is_transient(self):
        with pytest.raises(AITransientError, match="rate limit") as excinfo:
            self._send_raising(_RateLimitError("slow down", 429))
        assert excinfo.value.overloaded is False

    @pytest.mark.parametrize("cls", [_RateLimitError, _APIStatusError])
    def test_billing_shaped_errors(self, cls):
        with pytest.raises(AIBillingError, match="Insufficient Anthropic credits") as excinfo:
            self._send_raising(cls("Your credit balance is too low", 400))
        assert excinfo.value.detail == "Your credit balance is too low"

    def test_overload(self):
        with pytest.raises(AITransientError) as excinfo:
            self._send_raising(_InternalServerError("overloaded_error", 529))
        assert excinfo.value.overloaded is True
        assert "overloaded_error" in excinfo.value.detail

    def test_connection_error(self):
        with pytest.raises(AITransientError, match="Could not reach"):
            self._send_raising(_APIConnectionError("dns"))

    def test_other_status(self):
        with pytest.raises(AITransientError, match="Anthropic API error 400: bad request"):
            self._send_raising(_APIStatusError("bad request", 400))

    def test_unknown_exception(self):
        with pytest.raises(AIError, match="Unexpected error: boom") as excinfo:
            self._send_raising(RuntimeError("boom"))
        assert type(excinfo.value) is AIError

    def test_original_exception_is_chained(self):
        original = _AuthenticationError("bad key", 401)
        with pytest.raises(AIAuthenticationError) as excinfo:
            self._send_raising(original)
        assert excinfo.value.__cause__ is original


def test_provider_capabilities():
    provider = _provider(api_key="sk-x")
    assert provider.supports_vision() is True
    assert provider.has_shared_access() is True
    assert _provider().has_shared_access() is False
    assert provider.get_vendor_name() == "Anthropic"
