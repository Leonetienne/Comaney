"""
Live tests of the local provider against a real OpenAI-compatible model
server, through the real httpx2 transport. Opt-in, see conftest.py:

  LOCAL_AI_TEST_BASE_URL   e.g. http://localhost:11434/v1 (required)
  LOCAL_AI_TEST_MODEL      model tag (required)
  LOCAL_AI_TEST_API_KEY    set when the server (or auth proxy) requires a key
  LOCAL_AI_TEST_VISION     true to run the image test

No auth:   LOCAL_AI_TEST_BASE_URL=http://localhost:11434/v1 LOCAL_AI_TEST_MODEL=qwen3.8:27b LOCAL_AI_TEST_VISION=true venv/bin/pytest tests/integration/ -v | tee logfile.log
With auth: see docs/src/docs/dev-manual/local-ai-dev-stack.md
"""
import base64
import io
import os

import pytest
from PIL import Image

from ai_providers import load_provider
from ai_providers.base import AIRequest, ImageInput, SystemPart
from ai_providers.errors import AIAuthenticationError
from ai_providers.openai_compat import http_fetch
from tests.unit.ai_fakes import TrialSideEffects, make_service

BASE_URL = os.environ.get("LOCAL_AI_TEST_BASE_URL", "")
MODEL = os.environ.get("LOCAL_AI_TEST_MODEL", "")
API_KEY = os.environ.get("LOCAL_AI_TEST_API_KEY", "")
VISION = os.environ.get("LOCAL_AI_TEST_VISION", "").lower() == "true"

needs_key = pytest.mark.skipif(not API_KEY, reason="server without auth (LOCAL_AI_TEST_API_KEY unset)")
needs_no_key = pytest.mark.skipif(bool(API_KEY), reason="server requires a key (LOCAL_AI_TEST_API_KEY set)")


def _provider(api_key=API_KEY, **extra):
    env = {
        "AI_PROVIDER_LOCAL_BASE_URL": BASE_URL,
        "AI_PROVIDER_LOCAL_MODEL": MODEL,
        "AI_PROVIDER_LOCAL_SUPPORTS_VISION": "true" if VISION else "false",
        "AI_PROVIDER_LOCAL_CENTS_PER_MTOK": "1",
        **({"AI_PROVIDER_LOCAL_API_KEY": api_key} if api_key else {}),
        **{f"AI_PROVIDER_LOCAL_{k}": v for k, v in extra.items()},
    }
    return load_provider("local", env)


class HeaderRecorder:
    """The real transport, recording the headers of each request."""

    def __init__(self):
        self.headers = []

    def __call__(self, url, headers, payload, timeout):
        self.headers.append(dict(headers))
        return http_fetch(url, headers, payload, timeout)


def _ask(provider, text, user_config=None, **request):
    request = AIRequest("live_test", [SystemPart("Answer briefly.")], text, max_tokens=4096, **request)
    return provider.send(request, user_config or {})


@pytest.fixture(scope="module")
def warm():
    """First request loads the model into memory; keeps that wait out of the other tests' failure messages."""
    _ask(_provider(), "Say OK.")


def test_plain_prompt_returns_text_usage_and_cost(warm):
    response = _ask(_provider(), "Reply with the single word: pong")
    assert response.text
    assert response.usage["total_tokens"] > 0
    # cents_per_mtok=1
    assert response.cost_cents == round(response.usage["input_tokens"] / 1e6 + response.usage["output_tokens"] / 1e6, 4)


@needs_no_key
def test_without_auth_sends_no_authorization_header(warm):
    provider = _provider(api_key="")
    recorder = HeaderRecorder()
    provider._fetch = recorder
    assert _ask(provider, "Reply with the single word: pong").text
    assert not any(k.lower() == "authorization" for k in recorder.headers[0])


@needs_key
def test_correct_key_works(warm):
    assert _ask(_provider(), "Reply with the single word: pong").text


@needs_key
def test_missing_key_rejected():
    with pytest.raises(AIAuthenticationError):
        _ask(_provider(api_key=""), "pong?")


@needs_key
def test_wrong_key_rejected():
    with pytest.raises(AIAuthenticationError):
        _ask(_provider(api_key=API_KEY + "-wrong"), "pong?")


@needs_key
def test_per_user_key_without_instance_key(warm):
    provider = _provider(api_key="", SHARED_ACCESS="false")
    assert not provider.has_shared_access()
    assert _ask(provider, "Reply with the single word: pong", user_config={"api_key": API_KEY}).text


@needs_key
def test_per_user_key_beats_wrong_instance_key(warm):
    provider = _provider(api_key=API_KEY + "-wrong")
    assert _ask(provider, "Reply with the single word: pong", user_config={"api_key": API_KEY}).text


@needs_key
def test_wrong_per_user_key_rejected_without_shared_side_effects(monkeypatch):
    side_effects = TrialSideEffects()
    side_effects.install(monkeypatch)
    service = make_service(_provider(api_key="", SHARED_ACCESS="false"), is_trial=False)
    service.user_config = {"api_key": API_KEY + "-wrong"}
    with pytest.raises(AIAuthenticationError):
        service.prompt_partnership_mapping("Reply with {}.", "Go.")
    assert side_effects.invalid_key_mails == 0 and side_effects.disabled == []


@pytest.mark.skipif(not VISION, reason="LOCAL_AI_TEST_VISION is not true")
def test_image_is_described(warm):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (220, 20, 20)).save(buf, "PNG")
    image = ImageInput(base64.b64encode(buf.getvalue()).decode(), "image/png")
    response = _ask(_provider(), "What is the main color of this image? Answer with one English word.", images=[image])
    assert "red" in response.text.lower()


def test_json_prompt_parses_through_aiservice(warm, monkeypatch):
    TrialSideEffects().install(monkeypatch)
    service = make_service(_provider(), is_trial=True)
    mappings = service.prompt_partnership_mapping(
        'Reply with only this JSON object and nothing else: {"mappings": [{"source": "Food", "target": "Groceries"}]}',
        "Go.",
    )
    assert mappings == [{"source": "Food", "target": "Groceries"}]
    assert service.last_usage["total_tokens"] > 0
