"""
The OpenAI-compatible provider base (ai_providers/openai_compat.py) driven
through a fake transport: message translation, auth header, base URL, body,
cost, usage and content parsing, every error mapping branch.
Run with: venv/bin/pytest tests/unit/test_ai_provider_openai_compat.py -v
"""
import json

import pytest

from ai_providers import openai_compat
from ai_providers.base import AIRequest, ConfigField, ImageInput, SystemPart
from ai_providers.errors import (
    AIAuthenticationError, AIBillingError, AIError, AIInvalidResponseError,
    AIRefusalError, AITransientError, AIVisionUnsupportedError,
)
from ai_providers.openai_compat import (
    HTTPResult, OpenAICompatibleProvider, TransportConnectionError, TransportTimeout,
)


class FakeTransport:
    """Records each call; answers with the queued outcomes (HTTPResult or exception)."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def ok(content="hello", usage=None, finish="stop"):
    body = {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}
    if usage is not False:
        body["usage"] = usage or {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}
    return HTTPResult(200, json.dumps(body))


class Compat(OpenAICompatibleProvider):
    """Minimal subclass: 10 cents per 1000 tokens."""

    def __init__(self, config=None, fetch=None, vision=False):
        super().__init__(config or {}, fetch=fetch)
        self.vision = vision

    def get_name(self):
        return "compat"

    def get_display_name(self):
        return "Compat AI"

    def get_base_url(self):
        return self.config("base_url")

    def get_config_fields(self):
        return [
            ConfigField("base_url", "Base URL", default="http://srv:8000/v1/"),
            ConfigField("model", "Model", default="m1"),
            ConfigField("api_key", "API key", secret=True),
            ConfigField("max_tokens", "Max tokens", default="1000"),
            ConfigField("timeout", "Timeout", default="42"),
        ]

    def supports_vision(self):
        return self.vision

    def calculate_cost(self, usage):
        return (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)) / 100


def _request(**kw):
    defaults = dict(feature="test", system=[SystemPart("A"), SystemPart("B", cacheable=False)], user_text="hi")
    defaults.update(kw)
    return AIRequest(**defaults)


class TestMessages:

    def test_system_parts_joined_into_one_message(self):
        msgs = OpenAICompatibleProvider.to_openai_messages(_request())
        assert msgs == [{"role": "system", "content": "A\n\nB"}, {"role": "user", "content": "hi"}]

    def test_no_system_message_without_parts(self):
        msgs = OpenAICompatibleProvider.to_openai_messages(_request(system=[]))
        assert msgs == [{"role": "user", "content": "hi"}]

    def test_images_as_data_uris_then_text(self):
        req = _request(images=[ImageInput("QUJD", "image/png"), ImageInput("REVG", "image/jpeg")])
        user = OpenAICompatibleProvider.to_openai_messages(req)[-1]
        assert user["content"] == [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,REVG"}},
            {"type": "text", "text": "hi"},
        ]


class TestRequest:

    def test_url_body_timeout(self):
        t = FakeTransport(ok())
        Compat(fetch=t).send(_request(max_tokens=4096), {})
        call = t.calls[0]
        assert call["url"] == "http://srv:8000/v1/chat/completions"
        assert set(call["payload"]) == {"model", "messages", "max_tokens"}
        assert call["payload"]["model"] == "m1"
        assert call["payload"]["max_tokens"] == 1000  # capped by the provider option
        assert call["timeout"] == 42.0

    def test_feature_max_tokens_below_cap_kept(self):
        t = FakeTransport(ok())
        Compat(fetch=t).send(_request(max_tokens=300), {})
        assert t.calls[0]["payload"]["max_tokens"] == 300

    @pytest.mark.parametrize("raw, expected", [
        ("http://srv/v1/", "http://srv/v1/chat/completions"),
        ("http://srv/v1///", "http://srv/v1/chat/completions"),
        (" http://srv/v1 ", "http://srv/v1/chat/completions"),
    ])
    def test_base_url_normalized(self, raw, expected):
        assert Compat({"base_url": raw}).chat_url() == expected

    def test_auth_header_with_instance_key(self):
        t = FakeTransport(ok())
        Compat({"api_key": "sk-inst"}, fetch=t).send(_request(), {})
        assert t.calls[0]["headers"]["Authorization"] == "Bearer sk-inst"

    def test_user_key_wins(self):
        t = FakeTransport(ok())
        Compat({"api_key": "sk-inst"}, fetch=t).send(_request(), {"api_key": "sk-user"})
        assert t.calls[0]["headers"]["Authorization"] == "Bearer sk-user"

    def test_no_auth_header_without_key(self):
        t = FakeTransport(ok())
        Compat(fetch=t).send(_request(), {})
        assert "Authorization" not in t.calls[0]["headers"]
        assert not any(k.lower() == "authorization" for k in t.calls[0]["headers"])

    def test_default_timeout_without_field(self):
        class NoTimeout(Compat):
            def get_config_fields(self):
                return [f for f in super().get_config_fields() if f.key != "timeout"]
        t = FakeTransport(ok())
        NoTimeout(fetch=t).send(_request(), {})
        assert t.calls[0]["timeout"] == float(OpenAICompatibleProvider.DEFAULT_TIMEOUT)

    def test_images_refused_without_vision(self):
        t = FakeTransport()
        with pytest.raises(AIVisionUnsupportedError):
            Compat(fetch=t).send(_request(images=[ImageInput("QUJD", "image/png")]), {})
        assert t.calls == []

    def test_images_sent_with_vision(self):
        t = FakeTransport(ok())
        Compat(fetch=t, vision=True).send(_request(images=[ImageInput("QUJD", "image/png")]), {})
        assert t.calls[0]["payload"]["messages"][-1]["content"][0]["type"] == "image_url"


class TestResponse:

    def test_text_usage_and_cost(self):
        r = Compat(fetch=FakeTransport(ok("  {\"a\": 1}  "))).send(_request(), {})
        assert r.text == '{"a": 1}'
        assert r.cost_cents == 15.0
        assert r.usage == {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500,
                           "cost_usd": 0.15, "cost_cents": 15.0}

    def test_cost_keeps_four_decimals(self):
        r = Compat(fetch=FakeTransport(ok(usage={"prompt_tokens": 1, "completion_tokens": 0}))).send(_request(), {})
        assert r.cost_cents == 0.01

    def test_missing_usage_costs_zero_and_logs_once(self, caplog, monkeypatch):
        monkeypatch.setattr(openai_compat, "_missing_usage_logged", set())
        p = Compat(fetch=FakeTransport(ok(usage=False), ok(usage=False)))
        with caplog.at_level("WARNING"):
            first = p.send(_request(), {})
            p.send(_request(), {})
        assert first.cost_cents == 0 and first.usage["total_tokens"] == 0
        assert sum("no token usage" in r.message for r in caplog.records) == 1

    def test_list_content_parts(self):
        content = [{"type": "text", "text": "a"}, {"type": "reasoning", "text": "x"}, {"type": "text", "text": "b"}]
        assert Compat(fetch=FakeTransport(ok(content))).send(_request(), {}).text == "ab"

    @pytest.mark.parametrize("body", ["not json", "{}", '{"choices": []}', '{"choices": [{}]}', '[]'])
    def test_unexpected_body_shape(self, body):
        with pytest.raises(AIInvalidResponseError):
            Compat(fetch=FakeTransport(HTTPResult(200, body))).send(_request(), {})

    def test_empty_content_is_invalid(self):
        with pytest.raises(AIInvalidResponseError):
            Compat(fetch=FakeTransport(ok(""))).send(_request(), {})

    def test_content_filter_is_refusal_with_usage(self):
        with pytest.raises(AIRefusalError) as e:
            Compat(fetch=FakeTransport(ok(None, finish="content_filter"))).send(_request(), {})
        assert e.value.usage["cost_cents"] == 15.0


class TestErrors:

    def _raise(self, outcome):
        with pytest.raises(AIError) as e:
            Compat(fetch=FakeTransport(outcome)).send(_request(), {})
        return e.value

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth(self, status):
        assert type(self._raise(HTTPResult(status, '{"error": {"message": "bad key"}}'))) is AIAuthenticationError

    def test_402_billing_with_detail(self):
        err = self._raise(HTTPResult(402, '{"error": {"message": "Insufficient Balance"}}'))
        assert type(err) is AIBillingError and err.detail == "Insufficient Balance"

    def test_429_billing_by_body(self):
        assert type(self._raise(HTTPResult(429, '{"error": {"message": "You exceeded your current quota"}}'))) is AIBillingError

    def test_429_rate_limit_transient(self):
        err = self._raise(HTTPResult(429, '{"error": {"message": "slow down"}}'))
        assert type(err) is AITransientError and not err.overloaded

    @pytest.mark.parametrize("status, overloaded", [(500, False), (502, True), (503, True), (504, True), (529, True)])
    def test_5xx_transient(self, status, overloaded):
        err = self._raise(HTTPResult(status, "upstream down"))
        assert type(err) is AITransientError and err.overloaded is overloaded
        assert err.detail == "upstream down"

    def test_other_4xx_names_status_and_message(self):
        err = self._raise(HTTPResult(422, '{"error": {"message": "unknown model m1"}}'))
        assert type(err) is AIError and "422" in str(err) and "unknown model m1" in str(err)

    def test_timeout(self):
        err = self._raise(TransportTimeout("read timed out"))
        assert type(err) is AITransientError and "did not answer in time" in str(err)

    def test_connection_error(self):
        err = self._raise(TransportConnectionError("refused"))
        assert type(err) is AITransientError and "Could not reach Compat AI" in str(err)

    def test_secret_never_in_error(self):
        with pytest.raises(AIError) as e:
            Compat({"api_key": "sk-secret-xyz"}, fetch=FakeTransport(HTTPResult(401, "nope"))).send(_request(), {})
        assert "sk-secret-xyz" not in str(e.value)
