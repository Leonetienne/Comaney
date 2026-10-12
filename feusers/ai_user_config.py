"""
A feuser's own AI settings (FeUser.ai_user_config): one entry per provider,
e.g. {"claude": {"api_key": "..."}}. The fields of an entry are whatever the
provider declares in get_user_fields(); everything here is generated from
those ConfigFields.

Reads and writes touch the active provider's entry only. Entries of other
providers are ignored on read, dropped on save and deleted by
purge_inactive_ai_config while a provider is active.

Django-free (form_field() imports Django lazily) for tests/unit/test_ai_user_config.py.
"""
from __future__ import annotations

from ai_providers.base import AIProvider, ConfigField, field_error, normalize_value

MASK = "********"
# form/field name prefix: the "api_key" field is posted as "ai_api_key" (id "id_ai_api_key")
FIELD_PREFIX = "ai_"
# errors from validate_user_config() that name no declared field
NON_FIELD = ""


def mask_secret(value: str) -> str:
    """Shown in place of a stored secret: the mask plus its last 4 characters."""
    return MASK + value[-4:] if value else ""


def is_masked(value: str) -> bool:
    """A submitted value that is the (unchanged) masked display of a secret."""
    return value.startswith(MASK)


def form_field_name(f: ConfigField) -> str:
    return FIELD_PREFIX + f.key


def form_field(f: ConfigField):
    """The Django form field for one user setting. Always optional, so clearing
    every field works; clean_submission() runs the checks."""
    from django import forms  # lazy: this module stays importable without Django

    attrs = {"autocomplete": "off", "maxlength": f.max_length}
    if f.secret:
        widget = forms.PasswordInput(render_value=True, attrs=attrs)
    elif f.choices:
        widget = forms.Select(choices=[("", "---")] + [(c, c) for c in f.choices])
    else:
        widget = forms.TextInput(attrs=attrs)
    # strip=False: a masked secret must arrive exactly as displayed
    return forms.CharField(label=f.label, help_text=f.help_text, required=False, strip=False, widget=widget)


def own_entry(config: dict | None, provider: AIProvider | None) -> dict:
    """The active provider's entry, limited to its declared user fields."""
    if provider is None or not isinstance(config, dict):
        return {}
    entry = config.get(provider.get_name())
    if not isinstance(entry, dict):
        return {}
    declared = {f.key for f in provider.get_user_fields()}
    return {k: v for k, v in entry.items() if k in declared and isinstance(v, str) and v}


def has_own_access(config: dict | None, provider: AIProvider | None) -> bool:
    """The feuser's own settings can serve requests with the active provider."""
    return provider is not None and provider.user_config_complete(own_entry(config, provider))


def purge_foreign(config: dict | None, active_name: str | None) -> dict:
    """config with only the active provider's entry. With no provider active
    config stays complete, so saved keys survive an upgrade until the admin
    sets AI_PROVIDER."""
    if not isinstance(config, dict):
        return {}
    if active_name is None:
        return dict(config)
    return {k: v for k, v in config.items() if k == active_name}


def initial_values(provider: AIProvider, config: dict | None) -> dict[str, str]:
    """Form display values per field key; secrets masked."""
    entry = own_entry(config, provider)
    return {
        f.key: mask_secret(entry.get(f.key, "")) if f.secret else entry.get(f.key, "")
        for f in provider.get_user_fields()
    }


def clean_submission(provider: AIProvider, submitted: dict[str, str], config: dict | None) -> tuple[dict, dict[str, str]]:
    """
    Validate a submitted form, keyed by field key. Returns (entry, errors):
    entry holds the non-empty values to store, errors maps a field key (or
    NON_FIELD) to a message.

    A secret submitted as its masked display keeps the stored value; an empty
    value clears it. Clearing every field is always allowed (it removes the
    own settings); otherwise the generic ConfigField checks run, then the
    provider's validate_user_config().
    """
    stored = own_entry(config, provider)
    fields = provider.get_user_fields()
    values: dict[str, str] = {}
    for f in fields:
        raw = (submitted.get(f.key) or "").strip()
        if f.secret and is_masked(raw):
            raw = stored.get(f.key, "")
        values[f.key] = normalize_value(f, raw)

    if not any(values.values()):
        return {}, {}

    errors: dict[str, str] = {}
    for f in fields:
        error = field_error(f, values[f.key], f.label)
        if error:
            errors[f.key] = error
    if not errors:
        declared = {f.key for f in fields}
        for key, message in provider.validate_user_config(dict(values)).items():
            errors[key if key in declared else NON_FIELD] = message
    if errors:
        return {}, errors
    return {k: v for k, v in values.items() if v}, {}


def with_entry(provider_name: str, entry: dict) -> dict:
    """The new ai_user_config after saving `entry` for the active provider.
    Holds only that provider's entry: other providers' entries are dropped."""
    return {provider_name: entry} if entry else {}


def export_value(config: dict | None, provider: AIProvider | None) -> dict:
    """ai_user_config for the account export. The active provider's secret
    fields are masked like in the form; every other value that is not a
    declared non-secret field (other providers' leftovers, which only exist
    while no provider is active, or undeclared keys) is fully masked."""
    if not isinstance(config, dict):
        return {}
    public = set()
    secret = set()
    if provider is not None:
        for f in provider.get_user_fields():
            (secret if f.secret else public).add(f.key)
    out = {}
    for name, entry in config.items():
        if not isinstance(entry, dict):
            out[name] = MASK
            continue
        active = provider is not None and name == provider.get_name()
        masked = {}
        for key, value in entry.items():
            if active and key in public:
                masked[key] = value
            elif active and key in secret:
                masked[key] = mask_secret(value) if isinstance(value, str) else MASK
            else:
                masked[key] = MASK if value else ""
        out[name] = masked
    return out


def parse_config_args(items: list[str] | None) -> dict[str, str]:
    """create_user's repeatable --ai-config KEY=VALUE: {key: value}. The value
    may contain '='. Raises ValueError on input without '=' or an empty key."""
    result = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        key = key.strip().lower()
        if not sep or not key:
            # message omits the item, it may be a bare secret
            raise ValueError("--ai-config expects KEY=VALUE.")
        result[key] = value
    return result
