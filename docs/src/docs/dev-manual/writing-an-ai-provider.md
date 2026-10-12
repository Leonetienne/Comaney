# Writing an AI Provider

An AI provider is one Python file in `ai_providers/` with exactly one `AIProvider` subclass. Comaney loads it when `AI_PROVIDER` equals the file name, hands it only its own `AI_PROVIDER_<NAME>_*` environment variables (prefix stripped, keys lower-cased) and validates them at startup. Admins add a community provider by mounting the file into the container; see [AI Providers](../admin-manual/ai-providers.md#adding-a-community-provider). How providers fit into the AI layer: [Architecture](architecture.md#ai-architecture).

Rules:

- The file must not import Django or touch the database, settings, emails or the trial flag; `ai_providers/` is imported from `comaney/settings.py`.
- `get_name()` must equal the file name (`ai_providers/openrouter.py` -> `"openrouter"`): lower-case letters, digits and underscores.
- A provider raises only the typed errors from `ai_providers/errors.py`. Trial side effects (disabling shared access, admin emails) belong to `AIService`, not to the provider.
- Never put a secret value into an error message or log line.

## Minimal example

A service speaking the OpenAI Chat Completions API only needs a base URL, its options and its prices; `OpenAICompatibleProvider` does the request, auth header, parsing and error mapping:

```python
"""OpenRouter (OpenAI-compatible)."""
from ai_providers.base import ConfigField
from ai_providers.openai_compat import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):

    def get_name(self):
        return "openrouter"

    def get_display_name(self):
        return "OpenRouter"

    def get_vendor_name(self):
        return "OpenRouter"

    def get_base_url(self):
        return "https://openrouter.ai/api/v1"

    def get_config_fields(self):
        return [
            ConfigField("api_key", "API key", secret=True),
            ConfigField("model", "Model", required=True),
            ConfigField("cents_per_mtok", "Cents per million tokens", pattern=r"[0-9]+(\.[0-9]+)?", default="0"),
        ]

    def get_user_fields(self):
        return [ConfigField("api_key", "OpenRouter API key", secret=True, required=True)]

    def has_shared_access(self):
        return bool(self.config("api_key"))

    def calculate_cost(self, usage):
        tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        return tokens / 1_000_000 * float(self.config("cents_per_mtok"))
```

`ai_providers/deepseek.py` and `ai_providers/local.py` are complete examples of this kind. A service with its own API subclasses `AIProvider` directly and implements `send()` (see `ai_providers/claude.py`).

## `ConfigField`

One option, declared as data. Instance fields come from `get_config_fields()` (environment variables), user fields from `get_user_fields()` (each user's account settings: Comaney generates the form, validation, masking and export from them).

| Attribute | Meaning |
|---|---|
| `key` | JSON key and env suffix: `api_key` -> `AI_PROVIDER_<NAME>_API_KEY` |
| `label` | Shown in forms and messages |
| `secret` | Masked in forms (`********` + last 4), exports, logs and error messages |
| `required` | Instance field: startup fails without it. User field: the user's own settings count as complete only with it |
| `help_text` | Hint under the form field |
| `pattern` | Regex the whole value must match |
| `max_length` | Default 255 |
| `choices` | Allowed values, matched case-insensitively; `config()` returns the declared spelling |
| `default` | Instance fields only |

Read an instance value with `self.config("key")` (default applied). Cross-field checks go into `validate_config()` (extend `super().validate_config()`, return a list of messages) and `validate_user_config(values)` (return `{field key: message}`).

## Getters

| Method | Default | Meaning |
|---|---|---|
| `get_name()` | required | File name |
| `get_display_name()` | required | Shown to users, e.g. "DeepSeek" |
| `get_vendor_name()` | `""` | Company the data is sent to; empty for self-hosted |
| `get_privacy_policy_url()` / `get_billing_url()` | `""` | Linked where relevant |
| `sends_data_off_server()` | `True` | `False` for a model on the admin's own hardware |
| `has_shared_access()` | `True` | The instance config alone can serve requests |
| `user_config_complete(values)` | all required user fields set | The user's own settings can serve requests |
| `supports_vision()` | `False` | Drives the receipt photo upload and the server-side image check |

## `send()`

`send(request, user_config) -> AIResponse`. `request` is an `AIRequest` (feature name, `system` as a list of `SystemPart`s, `user_text`, `images`, `max_tokens`). `user_config` holds the user's own settings, or is `{}` for shared access, in which case the instance config applies. Return `AIResponse(text, cost_cents, usage)`, with `cost_cents` rounded to 4 decimals and `usage` containing at least `input_tokens`, `output_tokens` and `total_tokens`.

## Errors

| Raise | When |
|---|---|
| `AIAuthenticationError` | Credentials rejected |
| `AIBillingError(message, detail=...)` | Out of balance or credits |
| `AITransientError(message, overloaded=..., detail=...)` | Rate limit, overload, timeout, connection failure |
| `AIRefusalError(message, usage=...)` | The model declined the request |
| `AIInvalidResponseError(raw)` | Unexpected response shape |
| `AIVisionUnsupportedError` | Images passed although `supports_vision()` is false |
| `AIError` | Anything else |

## Testing

Unit tests live in `tests/unit/` and run without Django, network or SDKs: inject the transport. `OpenAICompatibleProvider` takes `fetch=`, a callable `(url, headers, payload, timeout) -> HTTPResult(status, body)` that may raise `TransportTimeout` or `TransportConnectionError`; only the default `http_fetch` imports `httpx2`. Load the provider through `ai_providers.load_provider(name, environ)` to test its env vars and validation. See `tests/unit/test_ai_provider_openai_compat.py`, `test_ai_provider_deepseek.py` and `test_ai_provider_local.py`.
