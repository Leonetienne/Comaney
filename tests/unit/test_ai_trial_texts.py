"""
Admin email texts about the shared AI access name the active provider, its
shared-key env var and its billing page, and omit the billing link when the
provider has none.
Run with: venv/bin/pytest tests/unit/test_ai_trial_texts.py -v
"""
from ai_providers import load_provider
from budget.ai_trial import billing_text, invalid_key_text, shared_key_setting
from tests.unit.ai_fakes import FakeProvider

CLAUDE = load_provider("claude", {"AI_PROVIDER_CLAUDE_API_KEY": "sk-ant-x"})
LOCAL = load_provider("local", {"AI_PROVIDER_LOCAL_BASE_URL": "http://h:1/v1", "AI_PROVIDER_LOCAL_MODEL": "m"})


class TestSharedKeySetting:

    def test_provider_with_api_key_option(self):
        assert shared_key_setting(CLAUDE) == "AI_PROVIDER_CLAUDE_API_KEY"
        assert shared_key_setting(LOCAL) == "AI_PROVIDER_LOCAL_API_KEY"

    def test_provider_without_api_key_option_names_its_prefix(self):
        assert shared_key_setting(FakeProvider()) == "AI_PROVIDER_FAKE_*"


class TestInvalidKeyText:

    def test_names_provider_and_setting(self):
        text = invalid_key_text(CLAUDE)
        assert "Claude (Anthropic) rejected the shared API key" in text
        assert "AI_PROVIDER_CLAUDE_API_KEY" in text
        assert "AI_TRIAL_API_KEY" not in text

    def test_other_provider_never_mentions_anthropic(self):
        text = invalid_key_text(LOCAL)
        assert "Self-hosted model" in text and "AI_PROVIDER_LOCAL_API_KEY" in text
        assert "anthropic" not in text.lower()


class TestBillingText:

    def test_includes_billing_url(self):
        text = billing_text(CLAUDE, "credit balance too low", "https://c.example")
        assert "Claude (Anthropic)" in text
        assert CLAUDE.get_billing_url() in text
        assert "credit balance too low" in text
        assert "https://c.example/admin/ai-trial/" in text

    def test_omits_billing_link_when_empty(self):
        assert LOCAL.get_billing_url() == ""
        text = billing_text(LOCAL, "402", "https://c.example")
        assert "Top up the account with your AI service" in text
        assert "http" not in text.split("Top up")[1].split("\n")[0]
        assert "anthropic" not in text.lower()
