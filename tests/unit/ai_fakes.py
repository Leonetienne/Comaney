"""Shared stand-ins for unit-testing budget.ai_service.AIService without
Django settings, a database or a real AI provider."""
from decimal import Decimal

from ai_providers.base import AIProvider, AIResponse
from budget.ai_service import AIService


class FakeFeuser:
    def __init__(self, spent=None):
        self.ai_trial_budget_spent = spent
        self.save_calls = 0

    def save(self, update_fields=None):
        self.save_calls += 1


class FakeProvider(AIProvider):
    """Replays scripted outcomes: each entry is (text, cost_cents) or an
    exception to raise. Records every request and user_config it gets."""

    def __init__(self, *outcomes, vision=True):
        super().__init__({})
        self.outcomes = list(outcomes)
        self.vision = vision
        self.requests = []
        self.user_configs = []

    def get_name(self):
        return "fake"

    def get_display_name(self):
        return "Fake AI"

    def supports_vision(self):
        return self.vision

    def send(self, request, user_config):
        self.requests.append(request)
        self.user_configs.append(user_config)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        text, cost_cents = outcome
        return AIResponse(text=text, cost_cents=cost_cents, usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})


def make_service(provider, *, is_trial=True, spent=Decimal("0")):
    """An AIService wired to `provider`, skipping __init__'s settings-based
    access resolution (covered by the e2e tests)."""
    service = AIService.__new__(AIService)
    service.feuser = FakeFeuser(spent=spent)
    service.provider = provider
    service.is_trial = is_trial
    service.user_config = {} if is_trial else {"api_key": "sk-own"}
    service.trial_spent = float(spent)
    service.last_usage = None
    return service


class TrialSideEffects:
    """Records budget.ai_trial's side effects instead of touching the flag
    file or sending email. Install with install(monkeypatch)."""

    def __init__(self):
        self.disabled = []
        self.billing_mails = []
        self.invalid_key_mails = 0
        self.repair_mails = []

    def install(self, monkeypatch):
        from budget import ai_trial
        monkeypatch.setattr(ai_trial, "disable_trial", lambda reason="": self.disabled.append(reason))
        monkeypatch.setattr(ai_trial, "notify_admin_billing", lambda reason: self.billing_mails.append(reason))
        monkeypatch.setattr(ai_trial, "notify_admin_invalid_trial_key", self._invalid_key)
        monkeypatch.setattr(
            ai_trial, "notify_admin_json_repair_fallback",
            lambda feature, resolved: self.repair_mails.append((feature, resolved)),
        )
        return self

    def _invalid_key(self):
        self.invalid_key_mails += 1
