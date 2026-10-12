"""
The AI availability decision (budget/ai_availability.py) and AIService's use
of it: provider none, own settings complete/incomplete, shared access,
AI_TRIAL_USAGE_LIMIT=0 (no limit), limit reached, special budget, trial
disabled flag and disable_ai_ui.
Run with: venv/bin/pytest tests/unit/test_ai_availability.py -v
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

import ai_providers
from ai_providers.base import AIProvider, ConfigField
from budget.ai_availability import (
    NO_AI, AIAccess, ai_ui_available, resolve_access, shared_limit, unlimited_shared_warning,
)
from tests.unit.ai_fakes import FakeProvider

GOOD = '{"result": "good", "items": [{"title": "Coffee"}]}'


def _access(**kw):
    facts = dict(
        provider_active=True, own_complete=False, shared_available=True,
        global_limit=10.0, special_budget=None, spent=0.0, shared_disabled=False,
    )
    facts.update(kw)
    return resolve_access(**facts)


class TestSharedLimit:

    def test_positive_global_limit(self):
        assert shared_limit(10, None) == 10.0

    @pytest.mark.parametrize("limit", [0, 0.0, -1])
    def test_zero_global_limit_means_no_limit(self, limit):
        assert shared_limit(limit, None) is None

    def test_special_budget_overrides(self):
        assert shared_limit(0, 25) == 25.0
        assert shared_limit(10, 3) == 3.0

    def test_special_budget_zero_is_a_real_cap(self):
        assert shared_limit(10, 0) == 0.0


class TestResolveAccess:

    def test_no_provider(self):
        assert _access(provider_active=False, own_complete=True) == NO_AI
        assert not NO_AI.enabled and not NO_AI.usable

    def test_own_complete_wins_and_is_never_limited(self):
        a = _access(own_complete=True, spent=999, shared_disabled=True)
        assert a == AIAccess(enabled=True, has_access=True)
        assert a.usable

    def test_own_incomplete_without_shared_access(self):
        a = _access(shared_available=False)
        assert a.enabled and not a.has_access and not a.usable

    def test_shared_under_limit(self):
        a = _access(spent=4)
        assert (a.is_shared, a.limit, a.spent, a.blocked, a.usable) == (True, 10.0, 4, False, True)

    def test_shared_limit_reached_blocks(self):
        a = _access(spent=10)
        assert a.blocked and not a.usable and a.has_access

    def test_limit_zero_never_blocks(self):
        a = _access(global_limit=0, spent=1_000_000)
        assert a.limit is None and not a.blocked and a.usable

    def test_special_budget_blocks_at_its_value(self):
        assert _access(global_limit=0, special_budget=5, spent=5).blocked
        assert not _access(global_limit=0, special_budget=5, spent=4.9).blocked

    def test_trial_disabled_flag_stops_shared(self):
        a = _access(shared_disabled=True)
        assert a.has_access and a.shared_disabled and not a.usable


class TestUiAvailable:

    @pytest.mark.parametrize("access, disable_ui, expected", [
        (NO_AI, False, False),
        (AIAccess(enabled=True), False, False),                                   # no own, no shared
        (AIAccess(enabled=True, has_access=True), False, True),                   # own settings
        (AIAccess(enabled=True, has_access=True), True, False),                   # own, but hidden
        (AIAccess(enabled=True, has_access=True, is_shared=True), False, True),   # shared
        (AIAccess(enabled=True, has_access=True, is_shared=True, blocked=True), False, True),  # limit reached: page explains
        (AIAccess(enabled=True, has_access=True, is_shared=True, shared_disabled=True), False, False),
        (AIAccess(enabled=True, has_access=True, is_shared=True), True, False),
    ])
    def test_table(self, access, disable_ui, expected):
        assert ai_ui_available(access, disable_ui) is expected


class TestUnlimitedWarning:

    def test_warns_for_shared_access_with_limit_zero(self):
        assert "unlimited" in unlimited_shared_warning(True, 0)

    def test_silent_with_limit(self):
        assert unlimited_shared_warning(True, 5) is None

    def test_silent_without_shared_access(self):
        assert unlimited_shared_warning(False, 0) is None


class KeyProvider(FakeProvider):
    """FakeProvider with a required own api_key and switchable shared access."""

    def __init__(self, *outcomes, shared=True):
        super().__init__(*outcomes)
        self.shared = shared

    def get_user_fields(self):
        return [ConfigField("api_key", "Key", secret=True, required=True)]

    def has_shared_access(self):
        return self.shared


class Feuser:
    def __init__(self, config=None, spent="0", special=None):
        self.ai_user_config = config or {}
        self.ai_trial_budget_spent = Decimal(spent)
        self.special_ai_trial_budget = special
        self.saves = 0

    def save(self, update_fields=None):
        self.saves += 1


@pytest.fixture
def env(monkeypatch):
    """budget.ai_service with stand-in settings and trial flag; returns a
    setter for the active provider, the limit and the flag."""
    from budget import ai_service, ai_trial
    state = SimpleNamespace(disabled=False)
    monkeypatch.setattr(ai_service, "settings", SimpleNamespace(AI_TRIAL_USAGE_LIMIT=10.0))
    monkeypatch.setattr(ai_trial, "trial_is_disabled", lambda: state.disabled)
    previous = ai_providers.get_provider()

    def configure(provider, limit=10.0, disabled=False):
        ai_providers.set_provider(provider)
        ai_service.settings.AI_TRIAL_USAGE_LIMIT = limit
        state.disabled = disabled
        return ai_service

    yield configure
    ai_providers.set_provider(previous)


class TestAIServiceAccess:

    def test_provider_none_raises_disabled_without_touching_feuser(self, env):
        svc = env(None)
        with pytest.raises(svc.AIDisabledError):
            svc.AIService(object())

    def test_disabled_error_is_a_budget_error(self, env):
        svc = env(None)
        assert issubclass(svc.AIDisabledError, svc.AIBudgetExceededError)

    def test_access_for_anonymous(self, env):
        svc = env(KeyProvider())
        a = svc.AIService.access_for(None)
        assert a.is_shared and a.spent == 0.0

    def test_own_key_used_as_user_config(self, env):
        svc = env(KeyProvider())
        service = svc.AIService(Feuser({"fake": {"api_key": "k"}}, spent="50"))
        assert (service.is_trial, service.user_config) == (False, {"api_key": "k"})

    def test_shared_blocked_at_limit(self, env):
        svc = env(KeyProvider(), limit=10)
        with pytest.raises(svc.AIBudgetExceededError, match="exhausted"):
            svc.AIService(Feuser(spent="10"))

    def test_shared_trial_disabled_refuses(self, env):
        svc = env(KeyProvider(), disabled=True)
        with pytest.raises(svc.AIBudgetExceededError, match="temporarily unavailable"):
            svc.AIService(Feuser())

    def test_own_key_ignores_trial_flag_and_limit(self, env):
        svc = env(KeyProvider(), limit=1, disabled=True)
        assert svc.AIService(Feuser({"fake": {"api_key": "k"}}, spent="5")).is_trial is False

    def test_no_access_at_all(self, env):
        svc = env(KeyProvider(shared=False))
        with pytest.raises(svc.AIBudgetExceededError, match="No AI access"):
            svc.AIService(Feuser())

    def test_limit_zero_never_blocks_and_still_records_spend(self, env):
        svc = env(KeyProvider((GOOD, 2.5)), limit=0)
        feuser = Feuser(spent="100000")
        service = svc.AIService(feuser)
        assert service.is_trial and service.trial_limit is None
        service.prompt_express_expense_gen("system", "coffee")
        assert feuser.ai_trial_budget_spent == Decimal("100002.5")
        assert service.trial_spent == 100002.5

    def test_positive_limit_records_spend(self, env):
        svc = env(KeyProvider((GOOD, 1.25)), limit=10)
        feuser = Feuser(spent="2")
        svc.AIService(feuser).prompt_express_expense_gen("system", "coffee")
        assert feuser.ai_trial_budget_spent == Decimal("3.25")

    def test_trial_state_for_shape(self, env):
        svc = env(KeyProvider(), limit=0)
        assert svc.AIService.trial_state_for(Feuser(spent="3")) == (True, True, None, 3.0, False)
        svc = env(KeyProvider(), limit=10)
        assert svc.AIService.trial_state_for(Feuser(spent="12")) == (True, True, 10.0, 12.0, True)
        svc = env(None)
        assert svc.AIService.trial_state_for(Feuser()) == (False, False, None, 0.0, False)
