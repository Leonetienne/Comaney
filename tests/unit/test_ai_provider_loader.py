"""Provider loading, generic config validation and startup resolution in ai_providers/.
Run with: venv/bin/pytest tests/unit/test_ai_provider_loader.py -v"""
import importlib
import logging
import sys
import textwrap

import pytest

import ai_providers
from ai_providers import get_provider, load_provider, resolve_ai_provider, set_provider
from ai_providers.base import AIProvider, ConfigField, field_error
from ai_providers.claude import ClaudeProvider
from ai_providers.errors import ProviderConfigError

SECRET = "sk-very-secret-value-1234"

_FAKE_PROVIDER = '''
from ai_providers.base import AIProvider, ConfigField

class {cls}(AIProvider):
    def get_name(self):
        return {reported!r}

    def get_display_name(self):
        return "Fake"

    def get_config_fields(self):
        return [
            ConfigField("api_key", "API key", secret=True, required=True, pattern=r"sk-[a-z-]+", max_length=40),
            ConfigField("model", "Model", required=True),
            ConfigField("mode", "Mode", choices=("fast", "slow"), default="fast"),
            ConfigField("secret_mode", "Secret mode", secret=True, choices=("a", "b")),
            ConfigField("label", "Label", max_length=5),
        ]
'''


@pytest.fixture
def provider_dir(tmp_path, monkeypatch):
    """Lets a test drop provider files into the ai_providers package, the
    same way a community provider is bind-mounted into it."""
    monkeypatch.setattr(ai_providers, "__path__", [*ai_providers.__path__, str(tmp_path)])
    written = []

    def write(name, source):
        (tmp_path / f"{name}.py").write_text(textwrap.dedent(source))
        importlib.invalidate_caches()
        written.append(name)

    yield write
    for name in written:
        sys.modules.pop(f"ai_providers.{name}", None)


@pytest.fixture
def fake(provider_dir):
    """Writes a valid fake provider and returns a loader for it."""
    counter = iter(range(1000))

    def make(reported=None, cls="FakeProvider", source=None):
        name = f"fakeprov{next(counter)}"
        provider_dir(name, source or _FAKE_PROVIDER.format(cls=cls, reported=reported or name))
        return name
    return make


def _env(name, **fields):
    return {f"AI_PROVIDER_{name.upper()}_{k.upper()}": v for k, v in fields.items()}


VALID = {"api_key": "sk-abc", "model": "m1"}


@pytest.fixture(autouse=True)
def _reset_active_provider():
    yield
    set_provider(None)


class TestLoadProviderNames:

    def test_unknown_provider(self):
        with pytest.raises(ProviderConfigError, match="unknown AI provider"):
            load_provider("doesnotexist", {})

    @pytest.mark.parametrize("name", ["../x", "a.b", "Claude", "", "1abc", "claude-x", "__init__"])
    def test_invalid_names_are_rejected_before_import(self, name, monkeypatch):
        monkeypatch.setattr(importlib, "import_module", lambda *a: pytest.fail("must not import"))
        with pytest.raises(ProviderConfigError, match="not a valid provider name"):
            load_provider(name, {})

    def test_import_error_inside_provider(self, provider_dir):
        provider_dir("brokenimport", "import a_module_that_does_not_exist_xyz\n")
        with pytest.raises(ProviderConfigError, match="could not be imported"):
            load_provider("brokenimport", {})

    def test_exception_while_importing_provider(self, provider_dir):
        provider_dir("crashing", "raise RuntimeError('boom')\n")
        with pytest.raises(ProviderConfigError, match="could not be imported.*RuntimeError"):
            load_provider("crashing", {})

    def test_module_without_provider_class(self, provider_dir):
        provider_dir("noclass", "X = 1\n")
        with pytest.raises(ProviderConfigError, match="exactly one AIProvider subclass, found 0"):
            load_provider("noclass", {})

    def test_module_with_two_provider_classes(self, provider_dir):
        source = _FAKE_PROVIDER.format(cls="One", reported="twoclasses") + textwrap.dedent('''
            class Two(One):
                pass
        ''')
        provider_dir("twoclasses", source)
        with pytest.raises(ProviderConfigError, match="found 2"):
            load_provider("twoclasses", _env("twoclasses", **VALID))

    def test_imported_base_class_is_not_counted(self):
        # base.py itself defines only AIProvider, which is never a provider
        with pytest.raises(ProviderConfigError, match="found 0"):
            load_provider("base", {})

    def test_get_name_must_equal_file_name(self, fake):
        name = fake(reported="somethingelse")
        with pytest.raises(ProviderConfigError, match="get_name\\(\\) must equal the file name"):
            load_provider(name, _env(name, **VALID))

    def test_valid_provider_loads(self, fake):
        name = fake()
        provider = load_provider(name, _env(name, **VALID))
        assert provider.get_name() == name
        assert provider.config("model") == "m1"


class TestConfigValidation:

    def test_required_missing_names_the_env_var(self, fake):
        name = fake()
        with pytest.raises(ProviderConfigError, match=f"AI_PROVIDER_{name.upper()}_MODEL is required"):
            load_provider(name, _env(name, api_key="sk-abc"))

    def test_blank_counts_as_missing(self, fake):
        name = fake()
        with pytest.raises(ProviderConfigError, match="MODEL is required"):
            load_provider(name, _env(name, api_key="sk-abc", model="   "))

    def test_pattern_must_match_fully(self, fake):
        name = fake()
        with pytest.raises(ProviderConfigError, match="API_KEY has an invalid format"):
            load_provider(name, _env(name, api_key="sk-abc!", model="m"))

    def test_choices(self, fake):
        name = fake()
        with pytest.raises(ProviderConfigError, match=r"MODE must be one of fast, slow \(got 'medium'\)"):
            load_provider(name, _env(name, mode="medium", **VALID))

    def test_choices_are_case_insensitive_and_canonical(self, fake):
        name = fake()
        provider = load_provider(name, _env(name, mode="  SLOW ", **VALID))
        assert provider.config("mode") == "slow"

    def test_max_length(self, fake):
        name = fake()
        with pytest.raises(ProviderConfigError, match="LABEL must be at most 5 characters"):
            load_provider(name, _env(name, label="toolong", **VALID))

    def test_defaults_applied(self, fake):
        name = fake()
        provider = load_provider(name, _env(name, **VALID))
        assert provider.config("mode") == "fast"
        assert provider.config("label") == ""

    def test_all_errors_reported_together(self, fake):
        name = fake()
        with pytest.raises(ProviderConfigError) as exc:
            load_provider(name, _env(name, mode="x"))
        assert "API_KEY is required" in str(exc.value)
        assert "MODEL is required" in str(exc.value)
        assert "MODE must be one of" in str(exc.value)

    def test_undeclared_key_is_rejected_by_config(self, fake):
        name = fake()
        provider = load_provider(name, _env(name, **VALID))
        with pytest.raises(KeyError):
            provider.config("not_declared")

    @pytest.mark.parametrize("fields", [
        {"api_key": SECRET + "!", "model": "m"},                 # pattern
        {"api_key": SECRET * 3, "model": "m"},                   # max_length
        {"secret_mode": SECRET, **VALID},                        # choices
    ])
    def test_secret_value_never_in_error_message(self, fake, fields):
        name = fake()
        with pytest.raises(ProviderConfigError) as exc:
            load_provider(name, _env(name, **fields))
        assert SECRET not in str(exc.value)

    def test_field_error_ok_for_valid_value(self):
        assert field_error(ConfigField("k", "K", pattern=r"\d+"), "42", "K") is None


class TestPrefixIsolation:

    def test_provider_sees_only_its_own_prefixed_vars(self, fake):
        name = fake()
        other = "AI_PROVIDER_OTHER_API_KEY"
        environ = {**_env(name, **VALID), other: "sk-other", "DB_PASSWORD": "dbpw", "AI_TRIAL_USAGE_LIMIT": "5"}
        provider = load_provider(name, environ)
        assert provider._config == {"api_key": "sk-abc", "model": "m1"}

    def test_unknown_own_var_is_dropped_and_logged(self, fake, caplog):
        name = fake()
        with caplog.at_level(logging.WARNING, logger="ai_providers.base"):
            provider = load_provider(name, _env(name, apikey="typo", **VALID))
        assert "apikey" not in provider._config
        assert f"AI_PROVIDER_{name.upper()}_APIKEY" in caplog.text
        assert "typo" not in caplog.text


class TestResolveAiProvider:

    def test_none_means_no_ai_without_error(self):
        assert resolve_ai_provider({"AI_PROVIDER": "none", "AI_PROVIDER_CLAUDE_API_KEY": "x"}) == (None, None)

    def test_unset_without_ai_vars_means_no_ai(self):
        assert resolve_ai_provider({"DB_PASSWORD": "x"}) == (None, None)

    def test_empty_counts_as_unset(self):
        assert resolve_ai_provider({"AI_PROVIDER": " "}) == (None, None)

    @pytest.mark.parametrize("leftover", ["AI_TRIAL_API_KEY", "AI_PROVIDER_CLAUDE_EFFORT", "AI_PROVIDER_LOCAL_BASE_URL"])
    def test_unset_with_leftover_ai_vars_asks_to_set_ai_provider(self, leftover):
        provider, error = resolve_ai_provider({leftover: SECRET})
        assert provider is None
        assert "AI_PROVIDER is not set" in error
        assert leftover in error
        assert SECRET not in error

    def test_unset_with_empty_leftover_is_not_an_error(self):
        assert resolve_ai_provider({"AI_TRIAL_API_KEY": ""}) == (None, None)

    def test_unrelated_ai_vars_are_not_leftovers(self):
        environ = {"AI_TRIAL_USAGE_LIMIT": "10", "AI_TRIAL_DISABLED_FLAG": "/x", "AI_API_KEY_TESTS": "k"}
        assert resolve_ai_provider(environ) == (None, None)

    def test_load_error_becomes_message(self):
        provider, error = resolve_ai_provider({"AI_PROVIDER": "doesnotexist"})
        assert provider is None
        assert "unknown AI provider" in error

    def test_claude_without_key_loads(self):
        provider, error = resolve_ai_provider({"AI_PROVIDER": "claude"})
        assert error is None
        assert isinstance(provider, ClaudeProvider)
        assert provider.has_shared_access() is False


class TestLegacyTrialKeyAlias:

    def test_old_only_is_used_and_warned(self, caplog):
        with caplog.at_level(logging.WARNING, logger="ai_providers"):
            provider, error = resolve_ai_provider({"AI_PROVIDER": "claude", "AI_TRIAL_API_KEY": SECRET})
        assert error is None
        assert provider.config("api_key") == SECRET
        assert "deprecated" in caplog.text
        assert SECRET not in caplog.text

    def test_new_only(self, caplog):
        with caplog.at_level(logging.WARNING, logger="ai_providers"):
            provider, error = resolve_ai_provider({"AI_PROVIDER": "claude", "AI_PROVIDER_CLAUDE_API_KEY": SECRET})
        assert error is None
        assert provider.config("api_key") == SECRET
        assert "deprecated" not in caplog.text

    def test_both_equal(self):
        provider, error = resolve_ai_provider(
            {"AI_PROVIDER": "claude", "AI_TRIAL_API_KEY": SECRET, "AI_PROVIDER_CLAUDE_API_KEY": SECRET})
        assert error is None
        assert provider.config("api_key") == SECRET

    def test_both_different_is_misconfigured(self):
        provider, error = resolve_ai_provider(
            {"AI_PROVIDER": "claude", "AI_TRIAL_API_KEY": SECRET, "AI_PROVIDER_CLAUDE_API_KEY": "sk-other"})
        assert provider is None
        assert "AI_TRIAL_API_KEY and AI_PROVIDER_CLAUDE_API_KEY are both set but differ" in error
        assert SECRET not in error and "sk-other" not in error

    def test_old_key_ignored_for_other_provider(self, fake, caplog):
        name = fake()
        with caplog.at_level(logging.WARNING, logger="ai_providers"):
            provider, error = resolve_ai_provider(
                {"AI_PROVIDER": name, "AI_TRIAL_API_KEY": SECRET, **_env(name, **VALID)})
        assert error is None
        assert provider.config("api_key") == "sk-abc"
        assert "ignored" in caplog.text


class TestClaudeConfig:

    def _load(self, **fields):
        return load_provider("claude", _env("claude", **fields))

    def test_defaults(self):
        provider = self._load()
        assert provider.config("model") == "claude-sonnet-5-5"
        assert provider.config("effort") == "medium"
        assert provider.config("max_tokens") == "8192"

    @pytest.mark.parametrize("value", ["low", "medium", "high", "xhigh", "max"])
    def test_every_documented_effort_is_accepted(self, value):
        assert self._load(effort=value).config("effort") == value

    def test_effort_case_and_whitespace_tolerated(self):
        assert self._load(effort="  HIGH ").config("effort") == "high"

    @pytest.mark.parametrize("value", ["minimal", "none", "1", "med"])
    def test_invalid_effort_names_the_env_var(self, value):
        with pytest.raises(ProviderConfigError) as exc:
            self._load(effort=value)
        assert "AI_PROVIDER_CLAUDE_EFFORT must be one of low, medium, high, xhigh, max" in str(exc.value)

    @pytest.mark.parametrize("field,value", [("max_tokens", "0"), ("max_tokens", "abc"), ("price_input", "-1"), ("price_output", "1,5")])
    def test_numeric_fields_validated(self, field, value):
        with pytest.raises(ProviderConfigError, match=f"AI_PROVIDER_CLAUDE_{field.upper()} has an invalid format"):
            self._load(**{field: value})

    def test_user_config_complete_needs_api_key(self):
        provider = self._load()
        assert provider.user_config_complete({"api_key": "sk-x"}) is True
        assert provider.user_config_complete({"api_key": " "}) is False
        assert provider.user_config_complete({}) is False


class TestActiveProvider:

    def test_set_and_get(self):
        provider = load_provider("claude", {})
        set_provider(provider)
        assert get_provider() is provider

    def test_default_is_none(self):
        assert get_provider() is None


def test_provider_without_user_fields_is_never_user_complete():
    class P(AIProvider):
        def get_name(self):
            return "p"
    assert P({}).user_config_complete({"anything": "x"}) is False
