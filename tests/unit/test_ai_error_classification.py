"""
AIService's handling of typed provider errors (budget/ai_service.py::AIService._call).

A provider maps its vendor errors to the typed errors in ai_providers/errors.py
(see test_ai_provider_claude.py). AIService adds the side effects of a failing
*shared* access, for every AI feature alike: an invalid shared key emails the
admin and shows a "server is misconfigured" message; an exhausted shared key
disables the trial and emails the admin. A feuser's own credentials never
trigger either.
Run with: venv/bin/pytest tests/unit/test_ai_error_classification.py -v
"""
import pytest

from ai_providers.errors import (
    AIAuthenticationError,
    AIBillingError,
    AIError,
    AIRefusalError,
    AITransientError,
)
from tests.unit.ai_fakes import FakeProvider, TrialSideEffects, make_service


@pytest.fixture
def effects(monkeypatch):
    return TrialSideEffects().install(monkeypatch)


def _prompt(service):
    return service.prompt_dashboard_card_yaml("system", "make a card")


class TestSharedAccess:

    def test_invalid_shared_key_notifies_admin_and_says_misconfigured(self, effects):
        provider = FakeProvider(AIAuthenticationError("Invalid API key. Please update it in your profile."))
        with pytest.raises(AIAuthenticationError) as excinfo:
            _prompt(make_service(provider, is_trial=True))
        assert "server is misconfigured" in str(excinfo.value)
        assert effects.invalid_key_mails == 1
        assert effects.disabled == []

    def test_exhausted_shared_key_disables_trial_and_notifies_admin(self, effects):
        provider = FakeProvider(AIBillingError("Insufficient credits.", detail="credit balance too low"))
        with pytest.raises(AIBillingError) as excinfo:
            _prompt(make_service(provider, is_trial=True))
        assert str(excinfo.value) == "credit balance too low"
        assert effects.disabled == ["credit balance too low"]
        assert effects.billing_mails == ["credit balance too low"]

    def test_transient_error_has_no_side_effects(self, effects):
        provider = FakeProvider(AITransientError("overloaded", overloaded=True, detail="529"))
        with pytest.raises(AITransientError) as excinfo:
            _prompt(make_service(provider, is_trial=True))
        assert excinfo.value.overloaded is True
        assert effects.disabled == [] and effects.billing_mails == [] and effects.invalid_key_mails == 0


class TestOwnCredentials:

    def test_invalid_own_key_keeps_provider_message_without_side_effects(self, effects):
        provider = FakeProvider(AIAuthenticationError("Invalid API key. Please update it in your profile."))
        with pytest.raises(AIAuthenticationError, match="update it in your profile"):
            _prompt(make_service(provider, is_trial=False))
        assert effects.invalid_key_mails == 0

    def test_own_billing_error_never_disables_the_trial(self, effects):
        provider = FakeProvider(AIBillingError("Insufficient credits. Please top up.", detail="raw"))
        with pytest.raises(AIBillingError, match="Please top up"):
            _prompt(make_service(provider, is_trial=False))
        assert effects.disabled == [] and effects.billing_mails == []

    def test_own_credentials_are_passed_to_the_provider(self, effects):
        provider = FakeProvider(('{"result": "good", "yaml": "a: 1"}', 0.1))
        _prompt(make_service(provider, is_trial=False))
        assert provider.user_configs == [{"api_key": "sk-own"}]

    def test_shared_access_passes_empty_user_config(self, effects):
        provider = FakeProvider(('{"result": "good", "yaml": "a: 1"}', 0.1))
        _prompt(make_service(provider, is_trial=True))
        assert provider.user_configs == [{}]


class TestUntypedProviderErrors:

    def test_untyped_exception_becomes_plain_ai_error(self, effects):
        provider = FakeProvider(RuntimeError("bug in a community provider"))
        with pytest.raises(AIError, match="Unexpected error: bug in a community provider") as excinfo:
            _prompt(make_service(provider))
        assert type(excinfo.value) is AIError

    def test_refusal_passes_through_and_is_billed(self, effects):
        provider = FakeProvider(AIRefusalError("declined", usage={"cost_cents": 0.5}))
        service = make_service(provider, is_trial=True)
        with pytest.raises(AIRefusalError, match="declined"):
            _prompt(service)
        assert float(service.feuser.ai_trial_budget_spent) == 0.5


def test_no_active_provider_blocks_before_anything_else(monkeypatch):
    from budget import ai_service
    from budget.ai_service import AIBudgetExceededError, AIService
    monkeypatch.setattr(ai_service, "get_provider", lambda: None)
    with pytest.raises(AIBudgetExceededError, match="not configured"):
        AIService(feuser=object())  # trial_state_for (settings) is never reached
