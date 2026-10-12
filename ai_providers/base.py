"""
Base class and data types every AI provider builds on. Django-free: this
package is imported from comaney/settings.py and from unit tests.

A provider is one file in ai_providers/ with one AIProvider subclass. It
declares its options as ConfigField data; the loader hands it only its own
AI_PROVIDER_<NAME>_* env vars, and the generic checks here validate them.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigField:
    """One option of a provider: an instance env var (get_config_fields) or a
    per-user setting (get_user_fields)."""
    key: str                    # env suffix / JSON key: "api_key" -> AI_PROVIDER_CLAUDE_API_KEY
    label: str
    secret: bool = False        # masked in forms, export, logs and error messages
    required: bool = False
    help_text: str = ""
    pattern: str = ""           # optional regex, must match the whole value
    max_length: int = 255
    choices: tuple[str, ...] = ()   # lower-case; values are matched case-insensitively
    default: str = ""           # instance fields only


@dataclass(frozen=True)
class SystemPart:
    text: str
    cacheable: bool = True      # the provider decides what to do with it (Claude: cache_control)


@dataclass(frozen=True)
class ImageInput:
    data_b64: str
    media_type: str


@dataclass(frozen=True)
class AIRequest:
    feature: str                # "express_creation", "dashboard_card_ai", ...
    system: list[SystemPart]
    user_text: str
    images: list[ImageInput] = field(default_factory=list)
    max_tokens: int = 4096      # what the feature needs; a provider may cap it


@dataclass(frozen=True)
class AIResponse:
    text: str
    cost_cents: float           # 4-decimal precision, see FeUser.ai_trial_budget_spent
    usage: dict                 # at least input_tokens / output_tokens / total_tokens


def env_var_name(provider_name: str, key: str) -> str:
    return f"AI_PROVIDER_{provider_name.upper()}_{key.upper()}"


def normalize_value(f: ConfigField, raw: str | None) -> str:
    """Stripped value; a choices field returns its canonical (declared) spelling."""
    value = (raw or "").strip()
    if f.choices:
        for choice in f.choices:
            if value.lower() == choice.lower():
                return choice
    return value


def field_error(f: ConfigField, raw: str | None, name: str) -> str | None:
    """Generic check of one value against its field, or None if it is fine.
    `name` is how the message refers to the field (env var or form label).
    A secret value is never echoed back."""
    value = normalize_value(f, raw)
    if not value:
        return f"{name} is required." if f.required else None
    shown = "" if f.secret else f" (got {value!r})"
    if len(value) > f.max_length:
        return f"{name} must be at most {f.max_length} characters long."
    if f.choices and value not in f.choices:
        return f"{name} must be one of {', '.join(f.choices)}{shown}."
    if f.pattern and not re.fullmatch(f.pattern, value):
        return f"{name} has an invalid format{shown}."
    return None


class AIProvider:
    """Base class for an AI provider. Subclasses override the getters and
    send(); everything provider-specific (model, prices, limits) lives in
    the subclass and is never read by Comaney's core."""

    def __init__(self, instance_config: dict[str, str]):
        # only this provider's own AI_PROVIDER_<NAME>_* vars, prefix stripped,
        # keys lower-cased; anything not declared is dropped so a typo is
        # visible in the log instead of silently ignored
        declared = {f.key: f for f in self.get_config_fields()}
        self._config: dict[str, str] = {}
        for key, value in instance_config.items():
            key = key.lower()
            if key in declared:
                self._config[key] = value
            else:
                _log.warning("Ignoring unknown AI provider setting %s", env_var_name(self.get_name(), key))

    def config(self, key: str) -> str:
        """Value of a declared instance field, default applied."""
        f = next((f for f in self.get_config_fields() if f.key == key), None)
        if f is None:
            raise KeyError(f"{self.get_name()} declares no config field {key!r}")
        return normalize_value(f, self._config.get(key)) or f.default

    # identity

    def get_name(self) -> str:
        """Must equal the provider's file name (ai_providers/<name>.py)."""
        raise NotImplementedError

    def get_display_name(self) -> str:
        raise NotImplementedError

    def get_vendor_name(self) -> str:
        return ""

    def get_privacy_policy_url(self) -> str:
        return ""

    def get_billing_url(self) -> str:
        return ""

    def sends_data_off_server(self) -> bool:
        return True

    # configuration

    def get_config_fields(self) -> list[ConfigField]:
        return []

    def get_user_fields(self) -> list[ConfigField]:
        return []

    def validate_config(self) -> list[str]:
        """Errors in the instance configuration; empty means OK. Subclasses
        adding their own checks extend super().validate_config()."""
        errors = []
        for f in self.get_config_fields():
            error = field_error(f, self._config.get(f.key), env_var_name(self.get_name(), f.key))
            if error:
                errors.append(error)
        return errors

    def validate_user_config(self, values: dict) -> dict[str, str]:
        """Cross-field checks of a user's own settings: {field key: message}."""
        return {}

    # access / capabilities

    def has_shared_access(self) -> bool:
        """The instance configuration alone can serve requests."""
        return True

    def user_config_complete(self, values: dict) -> bool:
        """The user's own settings can serve requests on their own."""
        fields = self.get_user_fields()
        return bool(fields) and all(
            normalize_value(f, values.get(f.key)) for f in fields if f.required
        )

    def supports_vision(self) -> bool:
        return False

    # the call

    def send(self, request: AIRequest, user_config: dict) -> AIResponse:
        """user_config is the user's own settings, or {} for shared access."""
        raise NotImplementedError
