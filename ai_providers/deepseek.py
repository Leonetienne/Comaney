"""
DeepSeek's hosted API (OpenAI-compatible, https://api.deepseek.com).
Billed at peak prices, which DeepSeek halves off-peak; shared-access budgets
stay on the safe side.
"""
from __future__ import annotations

from ai_providers.base import ConfigField
from ai_providers.openai_compat import OpenAICompatibleProvider

BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

# USD per MTok at peak: (input cache miss, output, input cache hit)
_FLASH = (0.30, 1.20, 0.006)
MODEL_PRICES = {
    "deepseek-flash": _FLASH,
    "deepseek-v4-pro": (1.32, 3.96, 0.044),
    # legacy names DeepSeek serves with the Flash model
    "deepseek-v4-flash": _FLASH,
    "deepseek-v4-flash-vision-exp": _FLASH,
}
VISION_MODELS = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}

_API_KEY_HELP = "A DeepSeek API key from platform.deepseek.com."
_PRICE_PATTERN = r"[0-9]+(\.[0-9]+)?"


class DeepSeekProvider(OpenAICompatibleProvider):
    # seconds; reasoning answers can take a while
    DEFAULT_TIMEOUT = 180

    def get_name(self) -> str:
        return "deepseek"

    def get_display_name(self) -> str:
        return "DeepSeek"

    def get_vendor_name(self) -> str:
        return "DeepSeek"

    def get_privacy_policy_url(self) -> str:
        return "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html"

    def get_billing_url(self) -> str:
        return "https://platform.deepseek.com/top_up"

    def get_base_url(self) -> str:
        return BASE_URL

    def get_config_fields(self) -> list[ConfigField]:
        return [
            # optional; empty = own keys only
            ConfigField("api_key", "API key", secret=True, help_text=_API_KEY_HELP),
            ConfigField("model", "Model", default=DEFAULT_MODEL),
            ConfigField("max_tokens", "Max tokens", pattern=r"[1-9][0-9]*", default="8192"),
            ConfigField("price_input", "Input price (USD per million tokens)", pattern=_PRICE_PATTERN),
            ConfigField("price_output", "Output price (USD per million tokens)", pattern=_PRICE_PATTERN),
        ]

    def get_user_fields(self) -> list[ConfigField]:
        return [ConfigField("api_key", "DeepSeek API key", secret=True, required=True, help_text=_API_KEY_HELP)]

    def validate_config(self) -> list[str]:
        errors = super().validate_config()
        has_in, has_out = bool(self.config("price_input")), bool(self.config("price_output"))
        if has_in != has_out:
            errors.append("Set both AI_PROVIDER_DEEPSEEK_PRICE_INPUT and AI_PROVIDER_DEEPSEEK_PRICE_OUTPUT, or neither.")
        elif not has_in and self.config("model") not in MODEL_PRICES:
            errors.append(
                f"No price is known for AI_PROVIDER_DEEPSEEK_MODEL={self.config('model')!r}. "
                "Set AI_PROVIDER_DEEPSEEK_PRICE_INPUT and AI_PROVIDER_DEEPSEEK_PRICE_OUTPUT "
                "(USD per million tokens)."
            )
        return errors

    def has_shared_access(self) -> bool:
        return bool(self.config("api_key"))

    def supports_vision(self) -> bool:
        return self.config("model") in VISION_MODELS

    def prices(self) -> tuple[float, float, float]:
        """(input cache miss, output, input cache hit) USD per MTok. An env
        override bills cache hits at the input price."""
        if self.config("price_input"):
            price_in = float(self.config("price_input"))
            return price_in, float(self.config("price_output")), price_in
        return MODEL_PRICES[self.config("model")]

    def calculate_cost(self, usage: dict) -> float:
        price_miss, price_out, price_hit = self.prices()
        prompt = int(usage.get("prompt_tokens") or 0)
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        miss = usage.get("prompt_cache_miss_tokens")
        miss = int(miss) if miss is not None else max(prompt - hit, 0)
        output = int(usage.get("completion_tokens") or 0)
        usd = (miss * price_miss + hit * price_hit + output * price_out) / 1_000_000
        return usd * 100
