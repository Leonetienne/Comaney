"""
Local (self-hosted) provider: required fields, defaults, optional auth, vision
flag parsing, max-token capping, cost per MTok, identity.
Run with: venv/bin/pytest tests/unit/test_ai_provider_local.py -v
"""
import json

import pytest

from ai_providers import load_provider
from ai_providers.base import AIRequest
from ai_providers.errors import ProviderConfigError
from ai_providers.openai_compat import HTTPResult

BASE = {"BASE_URL": "http://host.docker.internal:9931/v1", "MODEL": "qwen"}


def _env(**kw):
    return {"AI_PROVIDER": "local", **{f"AI_PROVIDER_LOCAL_{k}": v for k, v in {**BASE, **kw}.items()}}


def _load(**kw):
    return load_provider("local", _env(**kw))


class Recorder:
    def __init__(self, usage=None):
        self.usage = usage or {"prompt_tokens": 600_000, "completion_tokens": 400_000}
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        return HTTPResult(200, json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": self.usage}))


def _send(provider, rec, **request):
    provider._fetch = rec
    return provider.send(AIRequest("f", [], "u", **request), {})


class TestConfig:

    @pytest.mark.parametrize("missing", ["BASE_URL", "MODEL"])
    def test_required(self, missing):
        env = _env()
        del env[f"AI_PROVIDER_LOCAL_{missing}"]
        with pytest.raises(ProviderConfigError, match=f"AI_PROVIDER_LOCAL_{missing} is required"):
            load_provider("local", env)

    def test_base_url_must_be_http(self):
        with pytest.raises(ProviderConfigError, match="AI_PROVIDER_LOCAL_BASE_URL"):
            _load(BASE_URL="host:9931/v1")

    def test_defaults(self):
        p = _load()
        assert (p.config("max_tokens"), p.config("supports_vision"), p.config("cents_per_mtok"), p.config("timeout")) == (
            "8192", "false", "0", "600")

    def test_identity(self):
        p = _load()
        assert p.get_display_name() == "Self-hosted model"
        assert p.get_vendor_name() == ""
        assert not p.sends_data_off_server()
        assert p.has_shared_access()
        assert p.get_user_fields() == []

    def test_no_user_fields_means_never_own_access(self):
        assert not _load().user_config_complete({"api_key": "x"})

    @pytest.mark.parametrize("value, expected", [("true", True), ("TRUE", True), ("True", True), ("false", False)])
    def test_vision_flag(self, value, expected):
        assert _load(SUPPORTS_VISION=value).supports_vision() is expected

    def test_invalid_vision_flag(self):
        with pytest.raises(ProviderConfigError, match="AI_PROVIDER_LOCAL_SUPPORTS_VISION"):
            _load(SUPPORTS_VISION="yes")

    @pytest.mark.parametrize("field, value", [("CENTS_PER_MTOK", "-1"), ("TIMEOUT", "0"), ("MAX_TOKENS", "abc")])
    def test_invalid_numbers(self, field, value):
        with pytest.raises(ProviderConfigError, match=f"AI_PROVIDER_LOCAL_{field}"):
            _load(**{field: value})

    def test_api_key_value_never_in_errors(self):
        with pytest.raises(ProviderConfigError) as e:
            _load(API_KEY="sk-local-secret", MODEL="")
        assert "sk-local-secret" not in str(e.value)


class TestCall:

    def test_no_auth_header_without_key(self):
        rec = Recorder()
        _send(_load(), rec)
        assert "Authorization" not in rec.calls[0][1]

    def test_bearer_with_key(self):
        rec = Recorder()
        _send(_load(API_KEY="sk-local"), rec)
        assert rec.calls[0][1]["Authorization"] == "Bearer sk-local"

    def test_url_timeout_and_max_tokens(self):
        rec = Recorder()
        _send(_load(BASE_URL="http://h:11434/v1/", MAX_TOKENS="1024", TIMEOUT="30"), rec, max_tokens=8192)
        url, _, payload, timeout = rec.calls[0]
        assert url == "http://h:11434/v1/chat/completions"
        assert payload["max_tokens"] == 1024 and payload["model"] == "qwen"
        assert timeout == 30.0

    def test_cost_zero_by_default(self):
        assert _send(_load(), Recorder()).cost_cents == 0

    def test_cost_per_mtok(self):
        # 1M tokens total at 2.5 cents per MTok
        assert _send(_load(CENTS_PER_MTOK="2.5"), Recorder()).cost_cents == 2.5
