"""
Per-user AI settings (FeUser.ai_user_config): form field generation from a
provider's ConfigFields, masking, validation, saving only the active
provider's entry, purging inactive providers, export masking, create_user's
--ai-config parsing, and AIService's own-vs-shared access resolution.
Run with: venv/bin/pytest tests/unit/test_ai_user_config.py -v
"""
from types import SimpleNamespace

import pytest

import ai_providers
from ai_providers.base import AIProvider, ConfigField
from feusers import ai_user_config as cfg

SECRET = "sk-very-secret-value-1234"


class SettingsProvider(AIProvider):
    """A provider with one field of each kind plus a cross-field check."""

    def __init__(self, shared=True):
        super().__init__({})
        self.shared = shared

    def get_name(self):
        return "fake"

    def get_display_name(self):
        return "Fake AI"

    def get_user_fields(self):
        return [
            ConfigField("api_key", "Fake API key", secret=True, required=True, help_text="From fake.example"),
            ConfigField("region", "Region", choices=("eu", "us")),
            ConfigField("account", "Account id", pattern=r"[0-9]+", max_length=8),
        ]

    def validate_user_config(self, values):
        errors = {}
        if values.get("region") == "us" and not values.get("account"):
            errors["account"] = "An account id is required for the US region."
        if values.get("api_key") == "sk-banned":
            errors["something_else"] = "This key is banned."
        return errors

    def has_shared_access(self):
        return self.shared


class NoFieldsProvider(SettingsProvider):
    def get_user_fields(self):
        return []


@pytest.fixture
def provider():
    return SettingsProvider()


class TestFormFieldGeneration:

    def test_secret_field_is_password_input_showing_its_value(self, provider):
        field = cfg.form_field(provider.get_user_fields()[0])
        assert field.widget.input_type == "password"
        assert field.widget.render_value is True
        assert field.label == "Fake API key"
        assert field.help_text == "From fake.example"
        assert field.required is False
        assert field.strip is False

    def test_choices_field_is_select_with_empty_option(self, provider):
        field = cfg.form_field(provider.get_user_fields()[1])
        assert field.widget.input_type == "select"
        assert list(field.widget.choices) == [("", "---"), ("eu", "eu"), ("us", "us")]

    def test_text_field_is_text_input_with_max_length(self, provider):
        field = cfg.form_field(provider.get_user_fields()[2])
        assert field.widget.input_type == "text"
        assert field.widget.attrs["maxlength"] == 8

    def test_field_names_give_predictable_ids(self, provider):
        names = [cfg.form_field_name(f) for f in provider.get_user_fields()]
        assert names == ["ai_api_key", "ai_region", "ai_account"]

    def test_claude_declares_one_secret_api_key(self):
        from ai_providers.claude import ClaudeProvider
        fields = ClaudeProvider({}).get_user_fields()
        assert [(f.key, f.secret, f.required) for f in fields] == [("api_key", True, True)]


class TestMasking:

    def test_mask_shows_last_four(self):
        assert cfg.mask_secret(SECRET) == "********1234"

    def test_mask_of_empty_is_empty(self):
        assert cfg.mask_secret("") == ""

    def test_initial_values_mask_secrets_only(self, provider):
        config = {"fake": {"api_key": SECRET, "region": "eu", "account": "42"}}
        assert cfg.initial_values(provider, config) == {"api_key": "********1234", "region": "eu", "account": "42"}

    def test_initial_values_of_unset_fields_are_empty(self, provider):
        assert cfg.initial_values(provider, {}) == {"api_key": "", "region": "", "account": ""}

    def test_mask_round_trip_keeps_stored_value(self, provider):
        config = {"fake": {"api_key": SECRET}}
        shown = cfg.initial_values(provider, config)
        entry, errors = cfg.clean_submission(provider, shown, config)
        assert errors == {}
        assert entry == {"api_key": SECRET}


class TestCleanSubmission:

    def test_new_value_replaces_stored(self, provider):
        entry, errors = cfg.clean_submission(provider, {"api_key": "sk-new"}, {"fake": {"api_key": SECRET}})
        assert (entry, errors) == ({"api_key": "sk-new"}, {})

    def test_value_is_stripped(self, provider):
        entry, _ = cfg.clean_submission(provider, {"api_key": "  sk-new  "}, {})
        assert entry == {"api_key": "sk-new"}

    def test_empty_clears_everything(self, provider):
        entry, errors = cfg.clean_submission(provider, {"api_key": "", "region": ""}, {"fake": {"api_key": SECRET, "region": "eu"}})
        assert (entry, errors) == ({}, {})

    def test_masked_value_without_stored_value_clears(self, provider):
        assert cfg.clean_submission(provider, {"api_key": "********1234"}, {}) == ({}, {})

    def test_required_missing_while_other_fields_set(self, provider):
        entry, errors = cfg.clean_submission(provider, {"api_key": "", "region": "eu"}, {})
        assert entry == {}
        assert errors == {"api_key": "Fake API key is required."}

    def test_pattern_error_on_its_field(self, provider):
        _, errors = cfg.clean_submission(provider, {"api_key": "k", "account": "abc"}, {})
        assert errors == {"account": "Account id has an invalid format (got 'abc')."}

    def test_max_length_error(self, provider):
        _, errors = cfg.clean_submission(provider, {"api_key": "k", "account": "123456789"}, {})
        assert "at most 8" in errors["account"]

    def test_choice_matched_case_insensitively(self, provider):
        entry, errors = cfg.clean_submission(provider, {"api_key": "k", "region": "EU"}, {})
        assert (entry, errors) == ({"api_key": "k", "region": "eu"}, {})

    def test_invalid_choice(self, provider):
        _, errors = cfg.clean_submission(provider, {"api_key": "k", "region": "mars"}, {})
        assert "must be one of eu, us" in errors["region"]

    def test_secret_value_never_in_error(self):
        class Strict(SettingsProvider):
            def get_user_fields(self):
                return [ConfigField("api_key", "Key", secret=True, pattern=r"sk-[a-z]+")]
        _, errors = cfg.clean_submission(Strict(), {"api_key": SECRET}, {})
        assert errors == {"api_key": "Key has an invalid format."}

    def test_validate_user_config_error_shown_on_named_field(self, provider):
        _, errors = cfg.clean_submission(provider, {"api_key": "k", "region": "us"}, {})
        assert errors == {"account": "An account id is required for the US region."}

    def test_validate_user_config_error_on_unknown_key_is_non_field(self, provider):
        _, errors = cfg.clean_submission(provider, {"api_key": "sk-banned"}, {})
        assert errors == {cfg.NON_FIELD: "This key is banned."}

    def test_validate_user_config_not_run_on_generic_errors(self, provider):
        _, errors = cfg.clean_submission(provider, {"api_key": "sk-banned", "account": "x"}, {})
        assert list(errors) == ["account"]

    def test_undeclared_submitted_keys_are_ignored(self, provider):
        entry, _ = cfg.clean_submission(provider, {"api_key": "k", "evil": "x"}, {})
        assert entry == {"api_key": "k"}


class TestEntries:

    def test_own_entry_ignores_other_providers(self, provider):
        config = {"claude": {"api_key": "sk-claude"}, "fake": {"api_key": SECRET}}
        assert cfg.own_entry(config, provider) == {"api_key": SECRET}

    def test_own_entry_drops_undeclared_and_non_string_values(self, provider):
        config = {"fake": {"api_key": SECRET, "old_field": "x", "region": 3}}
        assert cfg.own_entry(config, provider) == {"api_key": SECRET}

    @pytest.mark.parametrize("config", [None, {}, {"fake": "oops"}, "oops", {"claude": {"api_key": "k"}}])
    def test_own_entry_empty_for_missing_or_malformed(self, provider, config):
        assert cfg.own_entry(config, provider) == {}

    def test_own_entry_without_provider(self):
        assert cfg.own_entry({"claude": {"api_key": "k"}}, None) == {}

    def test_has_own_access(self, provider):
        assert cfg.has_own_access({"fake": {"api_key": SECRET}}, provider)
        assert not cfg.has_own_access({"fake": {"region": "eu"}}, provider)
        assert not cfg.has_own_access({"claude": {"api_key": SECRET}}, provider)
        assert not cfg.has_own_access({"fake": {"api_key": SECRET}}, None)

    def test_no_user_fields_never_own_access(self):
        assert not cfg.has_own_access({"fake": {"api_key": SECRET}}, NoFieldsProvider())

    def test_saving_drops_other_providers_entries(self):
        assert cfg.with_entry("fake", {"api_key": "k"}) == {"fake": {"api_key": "k"}}

    def test_saving_empty_entry_leaves_empty_config(self):
        assert cfg.with_entry("fake", {}) == {}


class TestPurge:

    CONFIG = {"claude": {"api_key": "sk-claude"}, "local": {"base": "x"}, "fake": {"api_key": "k"}}

    def test_active_provider_keeps_its_entry(self):
        assert cfg.purge_foreign(self.CONFIG, "fake") == {"fake": {"api_key": "k"}}

    def test_others_removed_when_active_has_no_entry(self):
        assert cfg.purge_foreign(self.CONFIG, "deepseek") == {}

    def test_noop_without_active_provider(self):
        assert cfg.purge_foreign(self.CONFIG, None) == self.CONFIG

    def test_idempotent(self):
        once = cfg.purge_foreign(self.CONFIG, "claude")
        assert cfg.purge_foreign(once, "claude") == once == {"claude": {"api_key": "sk-claude"}}

    @pytest.mark.parametrize("config", [None, {}, "oops"])
    def test_empty_or_malformed_becomes_empty_dict(self, config):
        assert cfg.purge_foreign(config, "claude") == {}

    def test_migrated_claude_key_survives_with_no_provider_and_with_claude(self):
        migrated = {"claude": {"api_key": "sk-claude"}}
        assert cfg.purge_foreign(migrated, None) == migrated
        assert cfg.purge_foreign(migrated, "claude") == migrated


class TestExport:

    def test_active_entry_secret_masked_public_kept(self, provider):
        config = {"fake": {"api_key": SECRET, "region": "eu"}}
        assert cfg.export_value(config, provider) == {"fake": {"api_key": "********1234", "region": "eu"}}

    def test_undeclared_key_of_active_entry_fully_masked(self, provider):
        assert cfg.export_value({"fake": {"old": "secret-ish"}}, provider) == {"fake": {"old": "********"}}

    def test_leftover_entries_fully_masked(self, provider):
        config = {"claude": {"api_key": SECRET, "region": "eu"}}
        assert cfg.export_value(config, provider) == {"claude": {"api_key": "********", "region": "********"}}

    def test_without_provider_everything_fully_masked(self):
        config = {"claude": {"api_key": SECRET}}
        assert cfg.export_value(config, None) == {"claude": {"api_key": "********"}}

    def test_secret_never_in_export(self, provider):
        config = {"fake": {"api_key": SECRET}, "claude": {"api_key": SECRET}, "x": SECRET}
        assert SECRET not in repr(cfg.export_value(config, provider))

    def test_empty_values_stay_empty(self, provider):
        assert cfg.export_value({"claude": {"api_key": ""}}, provider) == {"claude": {"api_key": ""}}

    @pytest.mark.parametrize("config", [None, {}, "oops"])
    def test_empty_config(self, provider, config):
        assert cfg.export_value(config, provider) == {}


class TestParseConfigArgs:

    def test_key_value(self):
        assert cfg.parse_config_args(["api_key=sk-1", "Region=eu"]) == {"api_key": "sk-1", "region": "eu"}

    def test_value_containing_equals(self):
        assert cfg.parse_config_args(["api_key=a=b=="]) == {"api_key": "a=b=="}

    def test_empty_value_allowed(self):
        assert cfg.parse_config_args(["api_key="]) == {"api_key": ""}

    def test_none_or_empty(self):
        assert cfg.parse_config_args(None) == {}
        assert cfg.parse_config_args([]) == {}

    @pytest.mark.parametrize("item", ["sk-no-equals-sign", "=value", "  =x"])
    def test_invalid_input(self, item):
        with pytest.raises(ValueError) as e:
            cfg.parse_config_args([item])
        assert "KEY=VALUE" in str(e.value)

    def test_error_never_echoes_input(self):
        with pytest.raises(ValueError) as e:
            cfg.parse_config_args([SECRET])
        assert SECRET not in str(e.value)


class TestTrialStateFor:
    """AIService.trial_state_for() / __init__ access resolution with an
    active fake provider and stand-in Django settings."""

    @pytest.fixture
    def env(self, monkeypatch):
        from budget import ai_service
        monkeypatch.setattr(ai_service, "settings", SimpleNamespace(AI_TRIAL_USAGE_LIMIT=100))
        previous = ai_providers.get_provider()
        yield ai_service
        ai_providers.set_provider(previous)

    @staticmethod
    def _feuser(config=None, spent=0, special=None):
        return SimpleNamespace(
            ai_user_config=config or {}, ai_trial_budget_spent=spent,
            special_ai_trial_budget=special,
        )

    def test_no_provider(self, env):
        ai_providers.set_provider(None)
        assert env.AIService.trial_state_for(self._feuser({"fake": {"api_key": "k"}})) == (False, False, 0, 0, False)

    def test_own_complete_config_wins(self, env):
        ai_providers.set_provider(SettingsProvider())
        assert env.AIService.trial_state_for(self._feuser({"fake": {"api_key": "k"}})) == (True, False, 0, 0, False)

    def test_foreign_entry_falls_back_to_shared(self, env):
        ai_providers.set_provider(SettingsProvider())
        assert env.AIService.trial_state_for(self._feuser({"claude": {"api_key": "k"}}, spent=5)) == (True, True, 100.0, 5.0, False)

    def test_shared_blocked_at_limit(self, env):
        ai_providers.set_provider(SettingsProvider())
        assert env.AIService.trial_state_for(self._feuser(spent=100)) == (True, True, 100.0, 100.0, True)

    def test_special_budget_overrides_limit(self, env):
        ai_providers.set_provider(SettingsProvider())
        assert env.AIService.trial_state_for(self._feuser(special=10, spent=3))[2] == 10.0

    def test_no_shared_access_no_own(self, env):
        ai_providers.set_provider(SettingsProvider(shared=False))
        assert env.AIService.trial_state_for(self._feuser()) == (False, False, 0, 0, False)

    def test_service_gets_own_entry_as_user_config(self, env):
        ai_providers.set_provider(SettingsProvider())
        service = env.AIService(self._feuser({"fake": {"api_key": "k", "region": "eu"}, "claude": {"api_key": "x"}}))
        assert service.is_trial is False
        assert service.user_config == {"api_key": "k", "region": "eu"}

    def test_service_on_shared_access_gets_empty_user_config(self, env):
        ai_providers.set_provider(SettingsProvider())
        service = env.AIService(self._feuser({"claude": {"api_key": "x"}}))
        assert service.is_trial is True
        assert service.user_config == {}

    def test_service_without_any_access_raises(self, env):
        ai_providers.set_provider(SettingsProvider(shared=False))
        with pytest.raises(env.AIBudgetExceededError):
            env.AIService(self._feuser())
