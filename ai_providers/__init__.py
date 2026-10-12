"""
AI provider loading. Django-free: comaney/settings.py calls
resolve_ai_provider(os.environ) once at startup and registers the result
with set_provider(); the rest of the app reads it with get_provider().

Each provider is one file ai_providers/<name>.py holding one AIProvider
subclass. A community provider is added by mounting such a file into this
package and setting AI_PROVIDER=<name>.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import re
from collections.abc import Mapping

from ai_providers.base import AIProvider, env_var_name
from ai_providers.errors import ProviderConfigError

_log = logging.getLogger(__name__)

PROVIDER_ENV_VAR = "AI_PROVIDER"
NO_PROVIDER = "none"
# deprecated alias of AI_PROVIDER_CLAUDE_API_KEY
LEGACY_TRIAL_KEY_VAR = "AI_TRIAL_API_KEY"

_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")

_active: AIProvider | None = None


def set_provider(provider: AIProvider | None) -> None:
    global _active
    _active = provider


def get_provider() -> AIProvider | None:
    """The provider loaded at startup; None when AI is off."""
    return _active


def _provider_environ(name: str, environ: Mapping[str, str]) -> dict[str, str]:
    """Only AI_PROVIDER_<NAME>_* vars, prefix stripped, keys lower-cased."""
    prefix = env_var_name(name, "")
    return {k[len(prefix):].lower(): v for k, v in environ.items() if k.startswith(prefix) and len(k) > len(prefix)}


def _provider_class(name: str) -> type[AIProvider]:
    module_name = f"{__name__}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise ProviderConfigError(
                f"{PROVIDER_ENV_VAR}={name}: unknown AI provider. There is no file ai_providers/{name}.py."
            ) from None
        raise ProviderConfigError(f"{PROVIDER_ENV_VAR}={name}: the provider could not be imported ({exc}).") from None
    except Exception as exc:  # a broken community file must not crash startup with a traceback
        raise ProviderConfigError(
            f"{PROVIDER_ENV_VAR}={name}: the provider could not be imported ({type(exc).__name__}: {exc})."
        ) from None
    classes = [
        cls for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, AIProvider) and cls is not AIProvider and cls.__module__ == module_name
    ]
    if len(classes) != 1:
        raise ProviderConfigError(
            f"{PROVIDER_ENV_VAR}={name}: ai_providers/{name}.py must define exactly one AIProvider "
            f"subclass, found {len(classes)}."
        )
    return classes[0]


def load_provider(name: str, environ: Mapping[str, str]) -> AIProvider:
    """Import ai_providers/<name>.py, hand it its own env vars and validate
    them. Raises ProviderConfigError; messages never contain a secret."""
    if not _NAME_RE.fullmatch(name or ""):
        raise ProviderConfigError(
            f"{PROVIDER_ENV_VAR}={name!r} is not a valid provider name: use lower-case letters, "
            f"digits and underscores, starting with a letter (e.g. claude), or {NO_PROVIDER} to switch AI off."
        )
    cls = _provider_class(name)
    try:
        provider = cls(_provider_environ(name, environ))
        actual = provider.get_name()
    except Exception as exc:
        raise ProviderConfigError(
            f"{PROVIDER_ENV_VAR}={name}: the provider failed to start ({type(exc).__name__})."
        ) from None
    if actual != name:
        raise ProviderConfigError(
            f"{PROVIDER_ENV_VAR}={name}: the provider in ai_providers/{name}.py reports the name "
            f"{actual!r}; get_name() must equal the file name."
        )
    errors = provider.validate_config()
    if errors:
        raise ProviderConfigError(" ".join(errors))
    return provider


def _apply_legacy_trial_key(name: str, environ: Mapping[str, str]) -> Mapping[str, str]:
    """AI_TRIAL_API_KEY is the deprecated name of AI_PROVIDER_CLAUDE_API_KEY."""
    legacy = environ.get(LEGACY_TRIAL_KEY_VAR, "").strip()
    if not legacy:
        return environ
    if name != "claude":
        _log.warning("%s is ignored: it only applies to %s=claude.", LEGACY_TRIAL_KEY_VAR, PROVIDER_ENV_VAR)
        return environ
    new_var = env_var_name("claude", "api_key")
    current = environ.get(new_var, "").strip()
    if current and current != legacy:
        raise ProviderConfigError(
            f"{LEGACY_TRIAL_KEY_VAR} and {new_var} are both set but differ. "
            f"Remove {LEGACY_TRIAL_KEY_VAR}; it is deprecated."
        )
    _log.warning("%s is deprecated; rename it to %s.", LEGACY_TRIAL_KEY_VAR, new_var)
    return {**environ, new_var: legacy}


def _leftover_ai_vars(environ: Mapping[str, str]) -> list[str]:
    prefix = PROVIDER_ENV_VAR + "_"
    return sorted(
        k for k, v in environ.items()
        if v.strip() and (k == LEGACY_TRIAL_KEY_VAR or k.startswith(prefix))
    )


def resolve_ai_provider(environ: Mapping[str, str]) -> tuple[AIProvider | None, str | None]:
    """All AI startup logic: (provider or None, error message or None).

    AI_PROVIDER unset or empty means no AI, unless leftover AI settings show
    the admin meant to use AI (then it is an error, so an upgrade never turns
    AI off silently). AI_PROVIDER=none means no AI. Anything else is loaded."""
    name = environ.get(PROVIDER_ENV_VAR, "").strip()
    if not name:
        leftovers = _leftover_ai_vars(environ)
        if leftovers:
            return None, (
                f"AI settings are present ({', '.join(leftovers)}) but {PROVIDER_ENV_VAR} is not set. "
                f"Set {PROVIDER_ENV_VAR} to the AI provider to use (e.g. claude), "
                f"or to {NO_PROVIDER} to switch AI off."
            )
        return None, None
    if name == NO_PROVIDER:
        return None, None
    try:
        return load_provider(name, _apply_legacy_trial_key(name, environ)), None
    except ProviderConfigError as exc:
        return None, str(exc)
