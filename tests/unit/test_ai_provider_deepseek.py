"""
DeepSeek provider: config fields and defaults, price validation, vision per
model, max-token capping, cost with cache hit/miss tokens.
Run with: venv/bin/pytest tests/unit/test_ai_provider_deepseek.py -v
"""
import json

import pytest

from ai_providers import load_provider
from ai_providers.base import AIRequest, SystemPart
from ai_providers.deepseek import BASE_URL, DEFAULT_MODEL, MODEL_PRICES, DeepSeekProvider
from ai_providers.errors import ProviderConfigError
from ai_providers.openai_compat import HTTPResult


def _provider(fetch=None, **env):
    return DeepSeekProvider({k.lower(): v for k, v in env.items()}, fetch=fetch)


def _env(**kw):
    return {"AI_PROVIDER": "deepseek", **{f"AI_PROVIDER_DEEPSEEK_{k}": v for k, v in kw.items()}}


class Recorder:
    def __init__(self, usage):
        self.usage = usage
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        return HTTPResult(200, json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": self.usage}))


class TestConfig:

    def test_loads_with_defaults(self):
        p = load_provider("deepseek", _env())
        assert p.config("model") == DEFAULT_MODEL == "deepseek-flash"
        assert p.config("max_tokens") == "8192"
        assert p.chat_url() == BASE_URL + "/chat/completions"
        assert p.get_vendor_name() == "DeepSeek"

    def test_shared_access_only_with_instance_key(self):
        assert not _provider().has_shared_access()
        assert _provider(API_KEY="sk-1").has_shared_access()

    def test_user_field_is_a_required_secret_api_key(self):
        (f,) = _provider().get_user_fields()
        assert (f.key, f.secret, f.required) == ("api_key", True, True)
        assert _provider().user_config_complete({"api_key": "k"})
        assert not _provider().user_config_complete({})

    def test_unknown_model_needs_prices(self):
        with pytest.raises(ProviderConfigError, match="No price is known"):
            load_provider("deepseek", _env(MODEL="deepseek-future"))

    def test_unknown_model_with_prices_loads(self):
        p = load_provider("deepseek", _env(MODEL="deepseek-future", PRICE_INPUT="1", PRICE_OUTPUT="2"))
        assert p.prices() == (1.0, 2.0, 1.0)

    def test_one_price_alone_rejected(self):
        with pytest.raises(ProviderConfigError, match="or neither"):
            load_provider("deepseek", _env(PRICE_INPUT="1"))

    def test_invalid_max_tokens_rejected(self):
        with pytest.raises(ProviderConfigError, match="AI_PROVIDER_DEEPSEEK_MAX_TOKENS"):
            load_provider("deepseek", _env(MAX_TOKENS="0"))


class TestVision:

    @pytest.mark.parametrize("model, vision", [
        ("deepseek-flash", True),
        ("deepseek-v4-flash", True),
        ("deepseek-v4-flash-vision-exp", True),
        ("deepseek-v4-pro", False),
    ])
    def test_per_model(self, model, vision):
        assert _provider(MODEL=model).supports_vision() is vision

    @pytest.mark.parametrize("model, setting, vision", [
        ("deepseek-v4-pro", "true", True),
        ("deepseek-flash", "false", False),
    ])
    def test_override(self, model, setting, vision):
        assert _provider(MODEL=model, SUPPORTS_VISION=setting).supports_vision() is vision


class TestCall:

    def test_max_tokens_capped(self):
        rec = Recorder({"prompt_tokens": 1, "completion_tokens": 1})
        _provider(rec, MAX_TOKENS="2000").send(AIRequest("f", [SystemPart("s")], "u", max_tokens=8192), {})
        assert rec.calls[0][2]["max_tokens"] == 2000
        assert rec.calls[0][3] == 180.0

    def test_cost_with_cache_hit_and_miss(self):
        usage = {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 400_000,
                 "prompt_cache_miss_tokens": 600_000, "completion_tokens": 1_000_000}
        price_miss, price_out, price_hit = MODEL_PRICES["deepseek-flash"]
        expected = (0.6 * price_miss + 0.4 * price_hit + price_out) * 100
        r = _provider(Recorder(usage)).send(AIRequest("f", [], "u"), {})
        assert r.cost_cents == round(expected, 4)

    def test_cost_without_cache_fields_bills_all_input_as_miss(self):
        r = _provider(Recorder({"prompt_tokens": 1_000_000, "completion_tokens": 0}), MODEL="deepseek-v4-pro").send(
            AIRequest("f", [], "u"), {})
        assert r.cost_cents == round(MODEL_PRICES["deepseek-v4-pro"][0] * 100, 4)

    def test_price_override(self):
        r = _provider(Recorder({"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}),
                      PRICE_INPUT="1", PRICE_OUTPUT="3").send(AIRequest("f", [], "u"), {})
        assert r.cost_cents == 400.0
