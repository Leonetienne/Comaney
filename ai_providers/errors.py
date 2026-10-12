"""
Typed errors raised by AI providers and by budget.ai_service.AIService.

A provider raises only these; AIService re-exports them so existing
`from budget.ai_service import AIError, ...` imports keep working.
Django-free.
"""
from __future__ import annotations


class AIError(Exception):
    """Base class for every AI error."""


class AIRefusalError(AIError):
    """AI answered {"result": "fail", "msg": "..."}, or the provider's safety
    classifiers refused the request (even after any server-side fallback)."""
    def __init__(self, msg: str, raw: str = "", usage: dict | None = None):
        super().__init__(msg)
        self.raw = raw
        # classifier refusals only: cost of the declined attempts, billed by
        # AIService. Envelope "fail" usage is billed before raising.
        self.usage = usage


class AIInvalidResponseError(AIError):
    """AI returned unparseable or structurally unexpected output."""
    def __init__(self, raw: str = "", cause: Exception | None = None, usage: dict | None = None):
        super().__init__("Invalid response")
        self.raw = raw
        self.cause = cause
        # Set only when raised after a JSON-repair fallback was attempted --
        # the combined cost of the primary + repair calls, so the caller can
        # still bill it even though the request ultimately failed. None for
        # every other raise site (nothing extra was spent).
        self.usage = usage


class AIBudgetExceededError(AIError):
    """Trial or user budget is exhausted, or no usable AI access is configured at all."""


class AIAuthenticationError(AIError):
    """The configured credentials were rejected by the AI provider."""


class AIBillingError(AIError):
    """The shared credentials (or the feuser's own) are out of credits.
    The message is for the user; detail is the provider's raw error text."""
    def __init__(self, message: str, *, detail: str = ""):
        super().__init__(message)
        self.detail = detail or message


class AITransientError(AIError):
    """Rate limit, overload, or connectivity issue -- safe to retry later."""
    def __init__(self, message: str, *, overloaded: bool = False, detail: str = ""):
        super().__init__(message)
        self.overloaded = overloaded
        self.detail = detail


class AIVisionUnsupportedError(AIError):
    """Images were passed to a provider that cannot read them."""


class ProviderConfigError(Exception):
    """The AI provider could not be loaded or its instance configuration is
    invalid. Shown on the misconfigured page, so the message names the env
    var to fix but never contains a secret value. Not an AIError: it is a
    startup problem, never raised by a request."""
