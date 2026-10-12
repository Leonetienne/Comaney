"""
Claude by Anthropic. The only file allowed to name Anthropic in code, and the
only one that imports the `anthropic` SDK (lazily, inside send(), so loading
the provider at startup never needs it).
"""
from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace

from ai_providers.base import AIProvider, AIRequest, AIResponse, ConfigField
from ai_providers.errors import (
    AIAuthenticationError,
    AIBillingError,
    AIError,
    AIRefusalError,
    AITransientError,
)

_log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5"
# thinking is always on for this model, effort is the control
DEFAULT_EFFORT = "medium"
EFFORT_CHOICES = ("low", "medium", "high", "xhigh", "max")

# on a classifier refusal the API retries on Anthropic's recommended fallback model
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per MTok: (input, output, 5 min cache write, cache read); includes the
# fallback target (Sonnet 5 for Sonnet 5.5)
MODEL_PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-5":   (2.00, 10.00, 2.50, 0.20),
}
# Anthropic's cache multipliers, for a model priced via AI_PROVIDER_CLAUDE_PRICE_*
_CACHE_WRITE_FACTOR = 1.25
_CACHE_READ_FACTOR = 0.1

# pre-output refusals Anthropic bills; mid-output refusals are always billed
_BILLED_PRE_OUTPUT_REFUSALS = {"bio", "frontier_llm", "reasoning_extraction"}

REFUSAL_MESSAGE = "The AI declined this request. Rephrasing it or leaving out the objected part may help."

_API_KEY_HELP = "An Anthropic API key from console.anthropic.com."
_PRICE_PATTERN = r"[0-9]+(\.[0-9]+)?"


def compute_cost(input_tok: int, output_tok: int, cache_write_tok: int, cache_read_tok: int,
                 prices: tuple[float, float, float, float]) -> float:
    """USD cost of one attempt's token usage at the given per-MTok prices."""
    price_in, price_out, price_cw, price_cr = prices
    return (
        (input_tok       / 1_000_000) * price_in +
        (output_tok      / 1_000_000) * price_out +
        (cache_write_tok / 1_000_000) * price_cw +
        (cache_read_tok  / 1_000_000) * price_cr
    )


class ClaudeProvider(AIProvider):

    def __init__(self, instance_config: dict[str, str], sdk=None):
        """sdk: stand-in for the `anthropic` module (tests); imported lazily otherwise."""
        super().__init__(instance_config)
        self._sdk = sdk

    # identity

    def get_name(self) -> str:
        return "claude"

    def get_display_name(self) -> str:
        return "Claude (Anthropic)"

    def get_vendor_name(self) -> str:
        return "Anthropic"

    def get_privacy_policy_url(self) -> str:
        return "https://www.anthropic.com/legal/privacy"

    def get_billing_url(self) -> str:
        return "https://console.anthropic.com/settings/billing"

    # configuration

    def get_config_fields(self) -> list[ConfigField]:
        return [
            # optional: without it only users with their own key can use AI
            ConfigField("api_key", "API key", secret=True, help_text=_API_KEY_HELP),
            ConfigField("model", "Model", default=DEFAULT_MODEL),
            ConfigField("max_tokens", "Max tokens", pattern=r"[1-9][0-9]*", default="8192"),
            ConfigField("effort", "Effort", choices=EFFORT_CHOICES, default=DEFAULT_EFFORT),
            ConfigField("price_input", "Input price (USD per million tokens)", pattern=_PRICE_PATTERN),
            ConfigField("price_output", "Output price (USD per million tokens)", pattern=_PRICE_PATTERN),
        ]

    def get_user_fields(self) -> list[ConfigField]:
        return [ConfigField("api_key", "Anthropic API key", secret=True, required=True, help_text=_API_KEY_HELP)]

    def validate_config(self) -> list[str]:
        errors = super().validate_config()
        has_in, has_out = bool(self.config("price_input")), bool(self.config("price_output"))
        if has_in != has_out:
            errors.append("Set both AI_PROVIDER_CLAUDE_PRICE_INPUT and AI_PROVIDER_CLAUDE_PRICE_OUTPUT, or neither.")
        elif not has_in and self.config("model") not in MODEL_PRICES:
            # otherwise shared-access billing would silently be 0
            errors.append(
                f"No price is known for AI_PROVIDER_CLAUDE_MODEL={self.config('model')!r}. "
                "Set AI_PROVIDER_CLAUDE_PRICE_INPUT and AI_PROVIDER_CLAUDE_PRICE_OUTPUT "
                "(USD per million tokens)."
            )
        return errors

    # access / capabilities

    def has_shared_access(self) -> bool:
        return bool(self.config("api_key"))

    def supports_vision(self) -> bool:
        return True

    # pricing

    def model_prices(self, model: str) -> tuple[float, float, float, float]:
        """Per-MTok prices of a model that ran. The env override prices the
        configured model; an unknown model (e.g. a new fallback target) is
        billed at the configured model's rates, never at 0."""
        configured = self.config("model")
        if model == configured and self.config("price_input"):
            price_in, price_out = float(self.config("price_input")), float(self.config("price_output"))
            return price_in, price_out, price_in * _CACHE_WRITE_FACTOR, price_in * _CACHE_READ_FACTOR
        if model in MODEL_PRICES:
            return MODEL_PRICES[model]
        if model != configured:
            _log.warning("No price known for AI model %r; billing it at %s rates.", model, configured)
            return self.model_prices(configured)
        return MODEL_PRICES[DEFAULT_MODEL]  # unreachable once validate_config() passed

    def usage_from_response(self, response) -> dict:
        """Usage and cost of a response, each attempt in usage.iterations priced
        at its own model. Rescued declined attempts report no category, so
        they're billed."""
        u = response.usage
        iterations = list(getattr(u, "iterations", None) or [])
        if not iterations:
            iterations = [SimpleNamespace(
                model=getattr(response, "model", "") or self.config("model"),
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            )]

        final_unbilled_refusal = False
        if getattr(response, "stop_reason", None) == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            final_unbilled_refusal = category not in _BILLED_PRE_OUTPUT_REFUSALS

        totals = {"input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0}
        cost_usd = 0.0
        for index, attempt in enumerate(iterations):
            input_tok       = getattr(attempt, "input_tokens", 0) or 0
            output_tok      = getattr(attempt, "output_tokens", 0) or 0
            cache_write_tok = getattr(attempt, "cache_creation_input_tokens", 0) or 0
            cache_read_tok  = getattr(attempt, "cache_read_input_tokens", 0) or 0
            is_last = index == len(iterations) - 1
            if is_last and final_unbilled_refusal and output_tok == 0:
                continue
            totals["input_tokens"] += input_tok
            totals["output_tokens"] += output_tok
            totals["cache_write_tokens"] += cache_write_tok
            totals["cache_read_tokens"] += cache_read_tok
            model = getattr(attempt, "model", "") or self.config("model")
            cost_usd += compute_cost(input_tok, output_tok, cache_write_tok, cache_read_tok, self.model_prices(model))

        # cost_cents keeps the 4-decimal precision of FeUser.ai_trial_budget_spent:
        # rounding further would bill cheap, cache-heavy requests as 0
        return {
            **totals,
            "total_tokens": sum(totals.values()),
            "cost_usd": round(cost_usd, 6),
            "cost_cents": round(cost_usd * 100, 4),
        }

    def parse_response(self, response) -> AIResponse:
        """A refusal raises AIRefusalError with its usage; text is the first
        "text" block, thinking and fallback blocks may precede it."""
        usage = self.usage_from_response(response)

        if getattr(response, "stop_reason", None) == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            _log.warning("AI request refused by the model's safety classifiers (category=%r).", category)
            raise AIRefusalError(REFUSAL_MESSAGE, usage=usage)

        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text = block.text.strip()
                break

        if not text:
            _log.error("Claude returned an empty response. blocks: %r", response.content)
            raise AIError(
                "Unexpected error: Claude returned an empty response. Content blocks: "
                f"{[getattr(b, 'type', '?') for b in response.content]}"
            )
        return AIResponse(text=text, cost_cents=usage["cost_cents"], usage=usage)

    # the call

    @staticmethod
    def build_system(request: AIRequest) -> list[dict]:
        blocks = []
        for part in request.system:
            block = {"type": "text", "text": part.text}
            if part.cacheable:
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        return blocks

    @staticmethod
    def build_messages(request: AIRequest) -> list[dict]:
        if not request.images:
            return [{"role": "user", "content": request.user_text}]
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": img.media_type, "data": img.data_b64}}
            for img in request.images
        ]
        content.append({"type": "text", "text": request.user_text})
        return [{"role": "user", "content": content}]

    def send(self, request: AIRequest, user_config: dict) -> AIResponse:
        api_key = user_config.get("api_key", "") if user_config else self.config("api_key")
        sdk = self._sdk or importlib.import_module("anthropic")
        try:
            client = sdk.Anthropic(api_key=api_key)
            response = client.beta.messages.create(
                model=self.config("model"),
                max_tokens=min(request.max_tokens, int(self.config("max_tokens"))),
                system=self.build_system(request),
                messages=self.build_messages(request),
                output_config={"effort": self.config("effort")},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            return self.parse_response(response)
        except AIError:
            raise
        except Exception as exc:
            raise self.classify_exception(sdk, exc) from exc

    @staticmethod
    def classify_exception(sdk, exc: Exception) -> AIError:
        """Turn an anthropic SDK exception into a typed AIError. Most specific
        first: the rate-limit, server and connection errors are all
        APIStatusError/APIError subclasses."""
        if isinstance(exc, sdk.AuthenticationError):
            return AIAuthenticationError("Invalid API key. Please update it in your profile.")

        if isinstance(exc, sdk.PermissionDeniedError):
            return AIAuthenticationError(
                "API key does not have permission to use this model. Please check your Anthropic account."
            )

        if isinstance(exc, sdk.RateLimitError):
            if _looks_like_billing(exc):
                return _billing_error(exc)
            return AITransientError("Anthropic rate limit reached. Please wait a moment and try again.")

        if isinstance(exc, sdk.InternalServerError):
            return AITransientError(
                "Anthropic is temporarily overloaded. Please try again in a moment.",
                overloaded=True, detail=str(exc),
            )

        if isinstance(exc, sdk.APIConnectionError):
            return AITransientError("Could not reach the Anthropic API. Please check your internet connection.")

        if isinstance(exc, sdk.APIStatusError):
            if _looks_like_billing(exc):
                return _billing_error(exc)
            return AITransientError(f"Anthropic API error {exc.status_code}: {exc.message}")

        return AIError(f"Unexpected error: {exc}")


def _looks_like_billing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "credit" in msg or "billing" in msg or "balance" in msg


def _billing_error(exc: Exception) -> AIBillingError:
    return AIBillingError(
        "Insufficient Anthropic credits. Please top up your account at console.anthropic.com.",
        detail=str(exc),
    )
