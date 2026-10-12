"""
The one decision whether a feuser can use AI, for any provider. Pure and
Django-free: callers pass in plain facts, so every rule is unit-tested in
tests/unit/test_ai_availability.py. AIService.access_for() feeds it from the
live provider, settings and the trial-disabled flag.

Shared access is the instance's own provider config (e.g. the shared API
key). Its per-user monthly limit comes from AI_TRIAL_USAGE_LIMIT, where 0
means no limit; a feuser's special_ai_trial_budget overrides it and is
always a real cap (0 cents = nothing left). Own complete settings win over
shared access and skip Comaney's limit.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AIAccess:
    enabled: bool = False           # an AI provider is active
    has_access: bool = False        # own settings complete, or shared access exists
    is_shared: bool = False         # requests go through the shared access
    limit: float | None = None      # cents per month on shared access; None = no limit
    spent: float = 0.0              # cents spent on shared access this month
    blocked: bool = False           # shared limit reached
    shared_disabled: bool = False   # shared access switched off (billing error / admin)

    @property
    def usable(self) -> bool:
        """A request may be sent right now."""
        return self.has_access and not (self.is_shared and (self.blocked or self.shared_disabled))


NO_AI = AIAccess()


def shared_limit(global_limit: float, special_budget: int | None) -> float | None:
    """Monthly cap in cents for shared access; None = no limit."""
    if special_budget is not None:
        return float(special_budget)
    return float(global_limit) if global_limit > 0 else None


def resolve_access(
    *, provider_active: bool, own_complete: bool, shared_available: bool,
    global_limit: float, special_budget: int | None, spent: float, shared_disabled: bool,
) -> AIAccess:
    if not provider_active:
        return NO_AI
    if own_complete:
        return AIAccess(enabled=True, has_access=True)
    if not shared_available:
        return AIAccess(enabled=True)
    limit = shared_limit(global_limit, special_budget)
    return AIAccess(
        enabled=True, has_access=True, is_shared=True, limit=limit, spent=spent,
        blocked=limit is not None and spent >= limit,
        shared_disabled=shared_disabled,
    )


def ai_ui_available(access: AIAccess, disable_ai_ui: bool) -> bool:
    """AI entry points are shown. A reached limit keeps them visible, so the
    express page can explain the limit; a disabled shared access hides them."""
    if disable_ai_ui or not access.has_access:
        return False
    return not (access.is_shared and access.shared_disabled)


def vision_available(ai_available: bool, supports_vision: bool) -> bool:
    """Image input (receipt photos) is offered: AI is available and the
    provider reads images."""
    return ai_available and supports_vision


def unlimited_shared_warning(shared_available: bool, global_limit: float) -> str | None:
    """Startup warning text when shared access runs without a per-user limit."""
    if shared_available and global_limit <= 0:
        return (
            "AI shared access is configured with AI_TRIAL_USAGE_LIMIT=0: "
            "no per-user limit, spending on the shared access is unlimited."
        )
    return None
