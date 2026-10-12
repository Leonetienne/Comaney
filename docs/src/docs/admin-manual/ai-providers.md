# AI Providers

Comaney's AI features (AI Express Creation, the dashboard card assistant, Catalog Partnership mapping and Unclassified Expenses) work with one AI service at a time. You pick it with [`AI_PROVIDER`](environment-variables.md#ai_provider):

| `AI_PROVIDER` | Service | Data leaves your server | Reads receipt photos |
|---|---|---|---|
| `claude` | Claude by Anthropic | yes | yes |
| `deepseek` | DeepSeek | yes | depends on the model |
| `local` | Your own model on any OpenAI-compatible server | no (it goes to your own server) | if you say so |
| `none` or unset | AI switched off | | |

Each service has its own settings, all starting with `AI_PROVIDER_<NAME>_`. A service only ever sees its own settings. Invalid settings take the site down with a configuration error page naming the variable to fix.

How users get access, for every service except `local` (details in each section):

- **Shared access:** you set the service's API key, and every user without their own key uses it, limited per user by [`AI_TRIAL_USAGE_LIMIT`](environment-variables.md#ai_trial_usage_limit). See [AI Trial Key](ai-trial-key.md).
- **Own keys:** without a shared key, only users who enter their own key in their account settings can use AI.

When you switch to another service, users' saved settings of the previous one are deleted automatically (see [`purge_inactive_ai_config`](console-commands.md#purge_inactive_ai_config)).

---

## Claude (`claude`)

Claude by Anthropic, through Anthropic's API.

### Options

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `AI_PROVIDER_CLAUDE_API_KEY` | no | *(empty)* | Shared API key from [console.anthropic.com](https://console.anthropic.com). See Authentication. |
| `AI_PROVIDER_CLAUDE_MODEL` | no | `claude-sonnet-5-5` | Model. Comaney knows the prices of `claude-sonnet-5-5`; any other model also needs both prices below, otherwise the site shows a configuration error. |
| `AI_PROVIDER_CLAUDE_MAX_TOKENS` | no | `8192` | Upper limit for the length of one answer (whole number). |
| `AI_PROVIDER_CLAUDE_EFFORT` | no | `medium` | How much the model thinks: `low`, `medium`, `high`, `xhigh` or `max`. Higher is slower and costs more. |
| `AI_PROVIDER_CLAUDE_PRICE_INPUT` | no | *(built in)* | Input price in USD per million tokens. Set together with `_PRICE_OUTPUT` or not at all. |
| `AI_PROVIDER_CLAUDE_PRICE_OUTPUT` | no | *(built in)* | Output price in USD per million tokens. |

`AI_TRIAL_API_KEY` is the deprecated old name of `AI_PROVIDER_CLAUDE_API_KEY`; it still works with `AI_PROVIDER=claude` and logs a warning.

### Authentication

- **Shared key:** `AI_PROVIDER_CLAUDE_API_KEY`. Users without a key of their own use it, limited by `AI_TRIAL_USAGE_LIMIT`. Empty: no shared access.
- **Own key per user:** the account settings show the field **Anthropic API key** under "AI". A user's own key always wins over the shared key and is not limited by Comaney.
- The key is sent the way Anthropic's API expects it (`x-api-key` header, via Anthropic's SDK).

### Images

Receipt photos work with every supported Claude model.

### Cost

Computed from the token usage Anthropic reports, at the model's prices (or your price override). If the safety system declines a request, Anthropic may retry it on a fallback model; each attempt is billed at its own model's price.

### Example

```yaml
    environment:
      AI_PROVIDER: claude
      AI_PROVIDER_CLAUDE_API_KEY: "sk-ant-..."   # omit: only users with their own key
      AI_TRIAL_USAGE_LIMIT: 10
```

---

## DeepSeek (`deepseek`)

DeepSeek's hosted API at `https://api.deepseek.com` (OpenAI-compatible).

### Options

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `AI_PROVIDER_DEEPSEEK_API_KEY` | no | *(empty)* | Shared API key from [platform.deepseek.com](https://platform.deepseek.com). See Authentication. |
| `AI_PROVIDER_DEEPSEEK_MODEL` | no | `deepseek-flash` | Model. Comaney knows the prices of `deepseek-flash` and `deepseek-v4-pro`; any other model also needs both prices below. |
| `AI_PROVIDER_DEEPSEEK_MAX_TOKENS` | no | `8192` | Upper limit for the length of one answer (whole number). |
| `AI_PROVIDER_DEEPSEEK_PRICE_INPUT` | no | *(built in)* | Input price in USD per million tokens. Set together with `_PRICE_OUTPUT` or not at all. |
| `AI_PROVIDER_DEEPSEEK_PRICE_OUTPUT` | no | *(built in)* | Output price in USD per million tokens. |

### Authentication

- **Shared key:** `AI_PROVIDER_DEEPSEEK_API_KEY`. Users without a key of their own use it, limited by `AI_TRIAL_USAGE_LIMIT`. Empty: no shared access.
- **Own key per user:** the account settings show the field **DeepSeek API key** under "AI". A user's own key always wins over the shared key and is not limited by Comaney.
- The key is sent as `Authorization: Bearer <key>`.

### Images

Receipt photos work with `deepseek-flash` only; with any other model the photo upload is hidden.

### Cost

Computed from the token usage DeepSeek reports, with cached input billed at DeepSeek's lower cache price. DeepSeek halves its prices outside peak hours; Comaney always counts the peak price, so users' budgets are never undercharged. A price override bills cached input at the input price.

### Example

```yaml
    environment:
      AI_PROVIDER: deepseek
      AI_PROVIDER_DEEPSEEK_API_KEY: "sk-..."     # omit: only users with their own key
      AI_TRIAL_USAGE_LIMIT: 10
```

---

## Self-hosted model (`local`)

Any server that offers the OpenAI-compatible Chat Completions API (`POST <base URL>/chat/completions`): a model on your own hardware, or an OpenAI-compatible endpoint someone runs for you (for example your organisation's AI gateway).

### Options

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `AI_PROVIDER_LOCAL_BASE_URL` | yes | | Base URL **including the version part**, e.g. `http://host.docker.internal:11434/v1` or `https://ai.example.org/v1`. Must start with `http://` or `https://`. |
| `AI_PROVIDER_LOCAL_MODEL` | yes | | Model name exactly as the server knows it (e.g. `qwen3.8:27b`, or an alias such as `medium` on a gateway). |
| `AI_PROVIDER_LOCAL_API_KEY` | no | *(empty)* | Key for servers that require one. See Authentication. |
| `AI_PROVIDER_LOCAL_SUPPORTS_VISION` | no | `false` | `true` turns on the receipt photo upload. Set it only if the model and server read images. |
| `AI_PROVIDER_LOCAL_CENTS_PER_MTOK` | no | `0` | Cost in US cents per million tokens, input and output alike, counted against users' budgets. |
| `AI_PROVIDER_LOCAL_MAX_TOKENS` | no | `8192` | Upper limit for the length of one answer (whole number). |
| `AI_PROVIDER_LOCAL_TIMEOUT` | no | `600` | Seconds to wait for an answer. Models on modest hardware are slow, and the first request after a pause also loads the model. |

### Authentication

- **Without authentication:** leave `AI_PROVIDER_LOCAL_API_KEY` empty. Requests carry no `Authorization` header at all. Only for servers reachable from the Comaney container alone, never from the internet.
- **With authentication:** set `AI_PROVIDER_LOCAL_API_KEY`; it is sent as `Authorization: Bearer <key>`. Use the key the server was started with (e.g. `llama-server --api-key`, `vllm serve --api-key`), the token you created in the server (LM Studio), or the key the endpoint's operator gave you. For a server without its own key check, put a reverse proxy with authentication in front of it (see Common servers).
- **No own keys per user:** the account settings have no AI key field with this provider. Everyone uses the one configured key, limited per user by `AI_TRIAL_USAGE_LIMIT` (`0` for no limit).
- A wrong or missing key shows users "Self-hosted model rejected the API key".

### Images

Whether receipt photos work depends on the model and the server (some need an extra vision component, e.g. `--mmproj` for `llama-server`). Images are sent as base64 data URIs in `image_url` parts, so a gateway must accept those. Set `AI_PROVIDER_LOCAL_SUPPORTS_VISION=true` only after checking; otherwise the upload stays hidden.

### Cost

`AI_PROVIDER_LOCAL_CENTS_PER_MTOK` times the tokens the server reports (`prompt_tokens` + `completion_tokens`, which usually includes the model's thinking). A server that reports no token usage costs 0 (logged once). With the default `0`, usage is still recorded but costs nothing.

### Data protection

Comaney treats this provider as "data stays on your own server". That is true for a model on your own hardware; if `AI_PROVIDER_LOCAL_BASE_URL` points at someone else's endpoint, inform your users accordingly.

### Common servers

The table lists typical defaults; check the documentation of the version you run.

| Server | Typical base URL | Requiring an API key |
|---|---|---|
| llama.cpp (`llama-server`) | `http://<host>:9931/v1` | `--api-key <key>` (or `LLAMA_API_KEY`) |
| Ollama | `http://<host>:11434/v1` | No built-in key check; put a reverse proxy with authentication in front |
| LM Studio | `http://<host>:1234/v1` | Server Settings: **Require Authentication**, then create a token under **Manage Tokens** |
| vLLM (`vllm serve`) | `http://<host>:8000/v1` | `--api-key <key>` |
| SGLang | `http://<host>:30000/v1` | `--api-key <key>` |
| MLX-LM (`mlx_lm.server`) | `http://<host>:8080/v1` | No built-in key check; reverse proxy |
| LocalAI | `http://<host>:8080/v1` | `LOCALAI_API_KEY` (or `--api-keys`) |
| Docker Model Runner | `http://<host>:12434/engines/v1` | Ignores keys; reverse proxy |

### Where the server runs

- **Same host, server outside Docker:** use `http://host.docker.internal:<port>/v1`. On Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `web` service and let the server listen on an address the container can reach (not only `127.0.0.1`).
- **Mac:** Docker on macOS cannot give containers access to the GPU. Run the model server natively on the Mac (e.g. `llama-server` or Ollama installed with Homebrew) or with Docker Model Runner, and point Comaney at it as above.

### Examples

Without authentication, a server on the Docker host:

```yaml
    environment:
      AI_PROVIDER: local
      AI_PROVIDER_LOCAL_BASE_URL: "http://host.docker.internal:11434/v1"
      AI_PROVIDER_LOCAL_MODEL: "qwen3.8:27b"
      AI_PROVIDER_LOCAL_SUPPORTS_VISION: "true"
      AI_TRIAL_USAGE_LIMIT: 0                     # no per-user limit
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

With authentication, a server started with its own key:

```yaml
    environment:
      AI_PROVIDER: local
      AI_PROVIDER_LOCAL_BASE_URL: "http://host.docker.internal:9931/v1"
      AI_PROVIDER_LOCAL_MODEL: "qwen3.8"
      AI_PROVIDER_LOCAL_API_KEY: "a-long-random-string"   # the server's --api-key
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

With authentication, an OpenAI-compatible endpoint run by someone else:

```yaml
    environment:
      AI_PROVIDER: local
      AI_PROVIDER_LOCAL_BASE_URL: "https://ai.example.org/v1"
      AI_PROVIDER_LOCAL_MODEL: "medium"                   # the operator's model name or alias
      AI_PROVIDER_LOCAL_API_KEY: "sk-..."                 # from the operator
      AI_PROVIDER_LOCAL_CENTS_PER_MTOK: 50                # what the operator charges, if anything
```

---

## Adding a community provider

A provider is one Python file. Mount it into the container and select it by its file name:

```yaml
services:
  web:
    volumes:
      - ./openrouter.py:/app/ai_providers/openrouter.py:ro
    environment:
      AI_PROVIDER: openrouter
      AI_PROVIDER_OPENROUTER_API_KEY: "..."
```

The provider's own documentation lists its `AI_PROVIDER_<NAME>_*` settings. A file that cannot be loaded, or that rejects its settings, takes the site down with a configuration error page. Writing one: [Writing an AI provider](../dev-manual/writing-an-ai-provider.md).
