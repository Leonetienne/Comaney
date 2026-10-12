"""
Shared base for providers speaking the OpenAI Chat Completions API
(POST {base_url}/chat/completions): DeepSeek, any self-hosted server and
community providers. A subclass supplies the base URL, its config fields and
cost calculation; the request, auth header, response parsing and error
mapping live here.

The HTTP transport is injectable (fetch=) for unit tests; only http_fetch()
imports httpx2.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from ai_providers.base import AIProvider, AIRequest, AIResponse
from ai_providers.errors import (
    AIAuthenticationError,
    AIBillingError,
    AIError,
    AIInvalidResponseError,
    AIRefusalError,
    AITransientError,
    AIVisionUnsupportedError,
)

_log = logging.getLogger(__name__)

# provider classes whose missing `usage` was already logged in this process
_missing_usage_logged: set[str] = set()

_BILLING_WORDS = ("balance", "credit", "billing", "quota", "insufficient", "payment")


class TransportTimeout(Exception):
    """The server did not answer within the timeout."""


class TransportConnectionError(Exception):
    """The server could not be reached."""


@dataclass(frozen=True)
class HTTPResult:
    status: int
    body: str


Fetch = Callable[[str, dict, dict, float], HTTPResult]


def http_fetch(url: str, headers: dict, payload: dict, timeout: float) -> HTTPResult:
    """POST payload as JSON with httpx2, imported on the first request."""
    import httpx2

    try:
        response = httpx2.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx2.TimeoutException as exc:
        raise TransportTimeout(str(exc)) from exc
    except httpx2.TransportError as exc:
        raise TransportConnectionError(str(exc)) from exc
    return HTTPResult(response.status_code, response.text)


class OpenAICompatibleProvider(AIProvider):
    # seconds; used when the provider declares no "timeout" field
    DEFAULT_TIMEOUT = 120

    def __init__(self, instance_config: dict[str, str], fetch: Fetch | None = None):
        super().__init__(instance_config)
        self._fetch = fetch or http_fetch

    # to override

    def get_base_url(self) -> str:
        """Base URL up to and including the version part, e.g. http://host:11434/v1."""
        raise NotImplementedError

    def calculate_cost(self, usage: dict) -> float:
        """Cost in cents of one response's raw OpenAI `usage` object."""
        return 0.0

    # helpers

    def _declares(self, key: str) -> bool:
        return any(f.key == key for f in self.get_config_fields())

    def base_url(self) -> str:
        return self.get_base_url().strip().rstrip("/")

    def chat_url(self) -> str:
        return self.base_url() + "/chat/completions"

    def timeout(self) -> float:
        return float(self.config("timeout")) if self._declares("timeout") else float(self.DEFAULT_TIMEOUT)

    def max_tokens(self, request: AIRequest) -> int:
        if self._declares("max_tokens") and self.config("max_tokens"):
            return min(request.max_tokens, int(self.config("max_tokens")))
        return request.max_tokens

    def api_key(self, user_config: dict) -> str:
        if user_config:
            return user_config.get("api_key", "")
        return self.config("api_key") if self._declares("api_key") else ""

    @staticmethod
    def headers(api_key: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def to_openai_messages(request: AIRequest) -> list[dict]:
        """All system parts joined into one system message; images as data URIs."""
        messages = []
        system = "\n\n".join(part.text for part in request.system if part.text)
        if system:
            messages.append({"role": "system", "content": system})
        if not request.images:
            messages.append({"role": "user", "content": request.user_text})
            return messages
        content = [
            {"type": "image_url", "image_url": {"url": f"data:{img.media_type};base64,{img.data_b64}"}}
            for img in request.images
        ]
        content.append({"type": "text", "text": request.user_text})
        messages.append({"role": "user", "content": content})
        return messages

    def build_body(self, request: AIRequest) -> dict:
        return {
            "model": self.config("model"),
            "messages": self.to_openai_messages(request),
            "max_tokens": self.max_tokens(request),
        }

    # the call

    def send(self, request: AIRequest, user_config: dict) -> AIResponse:
        if request.images and not self.supports_vision():
            raise AIVisionUnsupportedError("The configured AI cannot read images.")
        name = self.get_display_name()
        try:
            result = self._fetch(self.chat_url(), self.headers(self.api_key(user_config)),
                                 self.build_body(request), self.timeout())
        except TransportTimeout:
            raise AITransientError(f"{name} did not answer in time. Please try again.")
        except TransportConnectionError:
            raise AITransientError(f"Could not reach {name}. Please try again later.")
        if result.status != 200:
            raise self.classify_status(result)
        return self.parse_response(result.body)

    def classify_status(self, result: HTTPResult) -> AIError:
        name = self.get_display_name()
        detail = _error_text(result.body)
        status = result.status
        if status in (401, 403):
            return AIAuthenticationError(f"{name} rejected the API key. Please check it.")
        if status == 402 or (status == 429 and _looks_like_billing(detail)):
            return AIBillingError(f"{name} reports insufficient balance.", detail=detail or f"HTTP {status}")
        if status == 429:
            return AITransientError(f"{name} rate limit reached. Please wait a moment and try again.")
        if status >= 500:
            return AITransientError(
                f"{name} is temporarily unavailable. Please try again in a moment.",
                overloaded=status in (502, 503, 504, 529), detail=detail,
            )
        return AIError(f"{name} error {status}: {detail or 'request rejected'}")

    def parse_response(self, body: str) -> AIResponse:
        try:
            data = json.loads(body)
            choice = data["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIInvalidResponseError(body, cause=exc)

        raw_usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(raw_usage, dict):
            cls = type(self).__name__
            if cls not in _missing_usage_logged:
                _missing_usage_logged.add(cls)
                _log.warning("%s returned no token usage; its requests are billed at 0.", self.get_display_name())
            raw_usage = {}
        usage = self.usage_from(raw_usage)

        text = _content_text(message.get("content") if isinstance(message, dict) else None)
        if choice.get("finish_reason") == "content_filter" and not text:
            raise AIRefusalError("The AI declined this request.", usage=usage)
        if not text:
            raise AIInvalidResponseError(body)
        return AIResponse(text=text, cost_cents=usage["cost_cents"], usage=usage)

    def usage_from(self, raw: dict) -> dict:
        input_tok = int(raw.get("prompt_tokens") or 0)
        output_tok = int(raw.get("completion_tokens") or 0)
        cost_cents = round(self.calculate_cost(raw), 4)
        return {
            "input_tokens": input_tok,
            "output_tokens": output_tok,
            "total_tokens": int(raw.get("total_tokens") or input_tok + output_tok),
            "cost_usd": round(cost_cents / 100, 6),
            "cost_cents": cost_cents,
        }


def _content_text(content) -> str:
    """Message content as text: a string, or a list of text parts."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        return "".join(parts).strip()
    return ""


def _error_text(body: str) -> str:
    """The server's error message, from {"error": {"message": ...}} or plain text."""
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()[:500]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
        if isinstance(error, str):
            return error[:500]
        if data.get("message"):
            return str(data["message"])[:500]
    return body.strip()[:500]


def _looks_like_billing(text: str) -> bool:
    text = text.lower()
    return any(word in text for word in _BILLING_WORDS)
