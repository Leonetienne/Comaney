"""
The provider-neutral AI-call orchestration in budget/ai_service.py, driven
through the real AIService with a scripted fake provider: request building
per feature, JSON repair, envelope handling, usage merging and trial billing.
Also the AI_NOTIFY_ADMIN_JSON_REPAIR switch in budget/ai_trial.py.
Run with: venv/bin/pytest tests/unit/test_ai_call_orchestration.py -v
"""
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from ai_providers.base import SystemPart
from budget.ai_service import AIInvalidResponseError, AIRefusalError
from budget.ai_service import _merge_usage as merge_usage
from budget.ai_service import _record_ai_usage as record_ai_usage
from tests.unit.ai_fakes import FakeFeuser, FakeProvider, TrialSideEffects, make_service

GOOD = '{"result": "good", "items": [{"title": "Coffee"}]}'


@pytest.fixture
def effects(monkeypatch):
    return TrialSideEffects().install(monkeypatch)


def _usage(cost_cents):
    return {
        "input_tokens": 10, "output_tokens": 5, "cache_write_tokens": 0,
        "cache_read_tokens": 0, "total_tokens": 15,
        "cost_usd": cost_cents / 100, "cost_cents": cost_cents,
    }


class TestMergeUsage:

    def test_sums_two_usages(self):
        merged = merge_usage(_usage(1.5), _usage(2.5))
        assert merged["cost_cents"] == 4.0
        assert merged["total_tokens"] == 30

    def test_single_usage_passthrough(self):
        merged = merge_usage(_usage(3.0))
        assert merged["cost_cents"] == 3.0
        assert merged["total_tokens"] == 15

    def test_keys_reported_by_only_one_provider_call_are_kept(self):
        merged = merge_usage({"cost_cents": 1.0, "reasoning_tokens": 7}, {"cost_cents": 0.5})
        assert merged == {"cost_cents": 1.5, "reasoning_tokens": 7}

    def test_cost_cents_keeps_four_decimals(self):
        assert merge_usage({"cost_cents": 0.00004}, {"cost_cents": 0.00004})["cost_cents"] == 0.0001


class TestRecordAiUsage:

    def test_noop_when_not_trial(self):
        feuser = FakeFeuser(spent=Decimal("1.0"))
        record_ai_usage(feuser, False, _usage(5.0))
        assert feuser.ai_trial_budget_spent == Decimal("1.0")
        assert feuser.save_calls == 0

    def test_noop_when_usage_falsy(self):
        feuser = FakeFeuser(spent=Decimal("1.0"))
        record_ai_usage(feuser, True, None)
        record_ai_usage(feuser, True, {})
        assert feuser.ai_trial_budget_spent == Decimal("1.0")
        assert feuser.save_calls == 0

    def test_accumulates_onto_existing_spend(self):
        feuser = FakeFeuser(spent=Decimal("1.0"))
        record_ai_usage(feuser, True, _usage(2.5))
        assert feuser.ai_trial_budget_spent == Decimal("3.5")
        assert feuser.save_calls == 1

    def test_starts_from_zero_when_unset(self):
        feuser = FakeFeuser(spent=None)
        record_ai_usage(feuser, True, _usage(0.75))
        assert feuser.ai_trial_budget_spent == Decimal("0.75")


class TestRequestsPerFeature:

    def test_express_text_only(self, effects):
        provider = FakeProvider((GOOD, 1.0))
        items = make_service(provider).prompt_express_expense_gen("sys", "coffee 3 euro")
        request = provider.requests[0]
        assert items == [{"title": "Coffee"}]
        assert request.feature == "express_creation"
        assert request.system == [SystemPart("sys")]
        assert request.user_text == "coffee 3 euro"
        assert request.images == []
        assert request.max_tokens == 8192

    def test_express_with_image_and_no_text(self, effects):
        provider = FakeProvider((GOOD, 1.0))
        make_service(provider).prompt_express_expense_gen("sys", "", image_b64="QUJD", image_type="image/png")
        request = provider.requests[0]
        assert [(i.data_b64, i.media_type) for i in request.images] == [("QUJD", "image/png")]
        assert "extract all expense items" in request.user_text

    def test_dashboard_card_keeps_system_parts(self, effects):
        provider = FakeProvider(('{"result": "good", "yaml": "type: cell"}', 1.0))
        parts = [SystemPart("docs"), SystemPart("context")]
        assert make_service(provider).prompt_dashboard_card_yaml(parts, "a card") == "type: cell"
        assert provider.requests[0].system == parts
        assert provider.requests[0].feature == "dashboard_card_ai"

    def test_partnership_mapping_has_no_envelope(self, effects):
        provider = FakeProvider(('{"mappings": [{"a": 1}]}', 1.0))
        assert make_service(provider).prompt_partnership_mapping("sys", "map these") == [{"a": 1}]
        assert provider.requests[0].max_tokens == 4096

    def test_unclassified_solve_has_no_envelope(self, effects):
        provider = FakeProvider(('{"category_idx": 2, "tag_idxs": "bad"}', 1.0))
        assert make_service(provider).prompt_unclassified_solve("sys") == {"category_idx": 2, "tag_idxs": []}
        assert provider.requests[0].feature == "unclassified_solve"


class TestEnvelope:

    def test_fail_envelope_is_a_refusal_and_still_billed(self, effects):
        service = make_service(FakeProvider(('{"result": "fail", "msg": "no expenses found"}', 0.5)))
        with pytest.raises(AIRefusalError, match="no expenses found"):
            service.prompt_express_expense_gen("sys", "hello")
        assert float(service.feuser.ai_trial_budget_spent) == 0.5

    def test_missing_result_is_invalid(self, effects):
        with pytest.raises(AIInvalidResponseError):
            make_service(FakeProvider(('{"items": []}', 0.5))).prompt_express_expense_gen("sys", "x")

    def test_non_object_is_invalid(self, effects):
        with pytest.raises(AIInvalidResponseError):
            make_service(FakeProvider(("[1, 2]", 0.5))).prompt_partnership_mapping("sys", "x")


class TestBilling:

    def test_success_bills_trial_and_sets_last_usage(self, effects):
        service = make_service(FakeProvider((GOOD, 1.25)), spent=Decimal("2"))
        service.prompt_express_expense_gen("sys", "x")
        assert service.feuser.ai_trial_budget_spent == Decimal("3.25")
        assert service.trial_spent == 3.25
        assert service.last_usage["cost_cents"] == 1.25
        assert service.last_usage["total_tokens"] == 15

    def test_own_credentials_are_not_billed_but_cost_is_shown(self, effects):
        service = make_service(FakeProvider((GOOD, 1.25)), is_trial=False, spent=Decimal("2"))
        service.prompt_express_expense_gen("sys", "x")
        assert service.feuser.ai_trial_budget_spent == Decimal("2")
        assert service.last_usage["cost_cents"] == 1.25


class TestJsonRepair:

    def test_repair_skipped_when_primary_parses(self, effects):
        provider = FakeProvider((GOOD, 1.0))
        make_service(provider).prompt_express_expense_gen("sys", "x")
        assert len(provider.requests) == 1
        assert effects.repair_mails == []

    def test_repair_recovers_broken_primary_response(self, effects):
        provider = FakeProvider(("Sure! Here's your JSON, hope it helps", 1.0), (GOOD, 0.5))
        service = make_service(provider)
        assert service.prompt_express_expense_gen("sys", "x") == [{"title": "Coffee"}]
        repair = provider.requests[1]
        assert repair.feature == "json_repair"
        assert repair.user_text == "Sure! Here's your JSON, hope it helps"
        assert repair.max_tokens == 8192
        assert "JSON repair" in repair.system[0].text
        # combined cost of both calls is billed, not just the repair call
        assert float(service.feuser.ai_trial_budget_spent) == 1.5
        assert effects.repair_mails == [("express_creation", True)]

    def test_repair_also_fails_bills_combined_usage(self, effects):
        provider = FakeProvider(("not json at all", 1.0), ("still not json", 0.5))
        service = make_service(provider)
        with pytest.raises(AIInvalidResponseError) as excinfo:
            service.prompt_express_expense_gen("sys", "x")
        assert excinfo.value.usage["cost_cents"] == 1.5
        assert float(service.feuser.ai_trial_budget_spent) == 1.5
        assert effects.repair_mails == [("express_creation", False)]

    def test_refused_repair_call_carries_combined_usage(self, effects):
        provider = FakeProvider(("not json at all", 1.0), AIRefusalError("declined", usage={"cost_cents": 0.25}))
        service = make_service(provider)
        with pytest.raises(AIRefusalError) as excinfo:
            service.prompt_express_expense_gen("sys", "x")
        assert excinfo.value.usage["cost_cents"] == 1.25
        assert float(service.feuser.ai_trial_budget_spent) == 1.25
        assert effects.repair_mails == []


class TestJsonRepairNotificationSwitch:

    @pytest.fixture
    def sent(self, monkeypatch):
        import django.core.mail
        sent = []
        monkeypatch.setattr(django.core.mail, "send_mail", lambda *args, **kwargs: sent.append(args))
        return sent

    def _settings(self, monkeypatch, notify):
        from budget import ai_trial
        monkeypatch.setattr(ai_trial, "settings", NS(
            DISABLE_EMAILING=False, ADMIN_NOTIFICATION_EMAIL="admin@example.com",
            DEFAULT_FROM_EMAIL="noreply@example.com", AI_NOTIFY_ADMIN_JSON_REPAIR=notify,
        ))

    def test_sends_when_enabled(self, monkeypatch, sent):
        from budget.ai_trial import notify_admin_json_repair_fallback
        self._settings(monkeypatch, True)
        notify_admin_json_repair_fallback("express_creation", resolved=True)
        assert len(sent) == 1
        assert "express_creation" in sent[0][0]

    def test_silent_when_disabled(self, monkeypatch, sent):
        from budget.ai_trial import notify_admin_json_repair_fallback
        self._settings(monkeypatch, False)
        notify_admin_json_repair_fallback("express_creation", resolved=False)
        assert sent == []
