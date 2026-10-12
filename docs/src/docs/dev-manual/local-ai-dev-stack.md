# Local AI in the Dev Stack

Run the dev stack against a self-hosted model (`AI_PROVIDER=local`) to exercise the local provider for real, with or without authentication. Plain `docker-compose up -d` is unaffected by everything on this page: the auth proxy only starts with its own Compose profile, and the model server runs outside Docker.

## Why the model runs outside Docker

Docker on macOS runs containers in a Linux VM (here Colima), and containers in that VM get no access to the Mac's GPU. A model server inside a container would run on the CPU only, which is far too slow. The model server therefore runs natively on the Mac, with Metal GPU acceleration, and the `web` container talks to it over the network.

The dev setup uses [Ollama](https://ollama.com). Any other OpenAI-compatible server works the same way (see [AI Providers](../admin-manual/ai-providers.md#common-servers)); nothing in Comaney's code or settings refers to a specific server.

## Install the model server

```bash
brew install ollama
brew services start ollama
```

`brew services` keeps it running in the background and starts it at login. It listens on `127.0.0.1:11434` only, so it is never reachable from the LAN. Check:

```bash
curl http://localhost:11434/v1/models
```

## The model

The dev setup uses **`qwen3.8:27b`**: the newest Qwen model with image input that fits this machine (Apple M2 Max, 64 GB; Colima's VM takes 16 GB of that). The download is 18 GB (4-bit `nvfp4` quantization, run by Ollama's MLX runner), and it occupies about 19 GB of memory once loaded (fully on the GPU). The larger Qwen mixture-of-experts preview (`qwen3.8-flash-next`, 105 GB) does not fit.

```bash
ollama pull qwen3.8:27b
```

It reads images, so receipt photos work: `AI_PROVIDER_LOCAL_SUPPORTS_VISION=true`.

Speed on the M2 Max: about 23 tokens per second (Ollama 0.40.3, MLX runner). The model thinks before answering; the thinking arrives separately and is not part of the answer text. The first request after the model was unloaded takes about 15 seconds longer while it loads; Ollama unloads it after 5 minutes without requests.

## How containers reach the Mac

Inside Colima's containers, `host.docker.internal` (and `host.lima.internal`) resolve to `192.168.5.2`, which Colima forwards to the Mac's own loopback interface, so the server can stay bound to `127.0.0.1`. The `web` service also maps `host.docker.internal` to `host-gateway` in `docker-compose.yml`, which on Colima is the same address and on Linux Docker is the host.

## Pointing the dev stack at a model

The dev stack is switched between AI services in `.env` only, then `web` is recreated so it reads the file. `.env` already contains a commented block for each variant below. Exactly one `AI_PROVIDER=` line may be active, otherwise one of them wins silently: comment out all others (including `AI_PROVIDER=claude`).

After every change to `.env`:

```bash
docker-compose up -d --force-recreate web
```

### Variant A: without authentication

`web` talks to Ollama on the Mac directly; no key, no `Authorization` header.

```
AI_PROVIDER=local
AI_PROVIDER_LOCAL_BASE_URL=http://host.docker.internal:11434/v1
AI_PROVIDER_LOCAL_MODEL=qwen3.8:27b
AI_PROVIDER_LOCAL_SUPPORTS_VISION=true
```

Check from inside the stack:

```bash
docker-compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/v1/models').read())"
```

### Variant B: with authentication, dev proxy in front of Ollama

Ollama has no API key check of its own. The Compose profile `ai-local-auth` starts a small Caddy proxy (`ai-auth-proxy`, config in `dev/ai-auth-proxy/Caddyfile`): it answers 401 to every request without `Authorization: Bearer ${LOCAL_AI_DEV_KEY}` and forwards the rest to Ollama on the Mac. An empty `LOCAL_AI_DEV_KEY` makes it refuse everything. Plain `docker-compose up -d` never starts it.

```
LOCAL_AI_DEV_KEY=<random string, already in .env>
AI_PROVIDER=local
AI_PROVIDER_LOCAL_BASE_URL=http://ai-auth-proxy:8080/v1
AI_PROVIDER_LOCAL_API_KEY=<same value as LOCAL_AI_DEV_KEY>
AI_PROVIDER_LOCAL_MODEL=qwen3.8:27b
AI_PROVIDER_LOCAL_SUPPORTS_VISION=true
```

Start the proxy, then recreate `web`:

```bash
docker-compose --profile ai-local-auth up -d
docker-compose up -d --force-recreate web
```

The proxy is also published on `127.0.0.1:18080` for checks and live tests from the Mac. Without the key it must answer 401, with the key 200:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:18080/v1/models
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer <LOCAL_AI_DEV_KEY>" http://localhost:18080/v1/models
```

Stop it again with `docker-compose --profile ai-local-auth stop ai-auth-proxy`.

### Variant C: with authentication, an external OpenAI-compatible endpoint

Any endpoint someone else runs (e.g. an organisation's AI gateway) works the same way, with the key its operator gave you. No proxy and no Ollama needed.

```
AI_PROVIDER=local
AI_PROVIDER_LOCAL_BASE_URL=https://<host>/v1
AI_PROVIDER_LOCAL_MODEL=<model name or alias of that endpoint>
AI_PROVIDER_LOCAL_API_KEY=<your key>
AI_PROVIDER_LOCAL_SUPPORTS_VISION=false
AI_PROVIDER_LOCAL_CENTS_PER_MTOK=<what the operator charges, or 0>
```

Set `AI_PROVIDER_LOCAL_SUPPORTS_VISION=true` once the operator confirms the model reads images. Check the key from the Mac (401 means the key is wrong or missing):

```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer <your key>" https://<host>/v1/models
```

The key lives only in your `.env`; never commit it.

**Per-user keys instead of the instance key.** For a gateway that gives each person their own key, leave `AI_PROVIDER_LOCAL_API_KEY` out and add `AI_PROVIDER_LOCAL_SHARED_ACCESS=false`; each account then enters its key under Profile, "AI", **API key**. The e2e tests give their accounts the key from `AI_API_KEY_TESTS_LOCAL` (the plain `AI_API_KEY_TESTS` is the Claude test key and is never sent to this provider).

### Back to Claude

Comment out every `AI_PROVIDER=local` and `AI_PROVIDER_LOCAL_*` line, restore `AI_PROVIDER=claude`, recreate `web`.

## Live tests

`tests/integration/test_local_provider_live.py` talks to a real server through the real HTTP transport. Default `pytest` runs never collect it; it runs only with `LOCAL_AI_TEST_BASE_URL` set.

Without auth, straight against the Mac's server:

```bash
LOCAL_AI_TEST_BASE_URL=http://localhost:11434/v1 LOCAL_AI_TEST_MODEL=qwen3.8:27b LOCAL_AI_TEST_VISION=true venv/bin/pytest tests/integration/ -v | tee logfile.log
```

With auth, through the dev proxy (variant B, profile running):

```bash
docker-compose --profile ai-local-auth up -d
LOCAL_AI_TEST_BASE_URL=http://localhost:18080/v1 LOCAL_AI_TEST_MODEL=qwen3.8:27b LOCAL_AI_TEST_API_KEY=<LOCAL_AI_DEV_KEY> LOCAL_AI_TEST_VISION=true venv/bin/pytest tests/integration/ -v | tee logfile.log
```

With auth, against an external endpoint (variant C; add `LOCAL_AI_TEST_VISION=true` only for a vision model):

```bash
LOCAL_AI_TEST_BASE_URL=https://<host>/v1 LOCAL_AI_TEST_MODEL=<model> LOCAL_AI_TEST_API_KEY=<your key> venv/bin/pytest tests/integration/ -v | tee logfile.log
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| AI Express shows "Could not reach Self-hosted model" | The server is not running: `brew services start ollama`, then `curl http://localhost:11434/v1/models`. |
| Error 404 mentioning the model | The model is not pulled, or the tag in `AI_PROVIDER_LOCAL_MODEL` is misspelled: `ollama list`, `ollama pull qwen3.8:27b`. |
| Works on the Mac, not from the stack | Check from inside the container: `docker-compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/version').read())"`. |
| 403 from the server through a proxy | Ollama accepts only local `Host` headers; the dev proxy rewrites `Host` to `localhost`. |
| "rejected the API key" | Variant B: `AI_PROVIDER_LOCAL_API_KEY` differs from `LOCAL_AI_DEV_KEY`. Variant C: the key is wrong. In both: `web` was not recreated after editing `.env`. |
| Site shows a configuration error after switching | A required `AI_PROVIDER_LOCAL_*` value is missing or invalid; the page names the variable. |
| Still the old AI service after switching | `web` not recreated, or a second `AI_PROVIDER=` line is still active (one of them wins silently). |
| First request takes long or times out | The model is loaded into memory on the first request after a while of inactivity. `AI_PROVIDER_LOCAL_TIMEOUT` (default 600 s) covers it; later requests are faster. |
