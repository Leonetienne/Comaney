"""
Verify the partnership onboarding wizard guards both AI buttons behind
{% if ai_smart_create_available %} so they are hidden when AI is unavailable.

No Django required: we inspect the template source directly.

Run with: venv/bin/pytest tests/unit/test_onboarding_ai_button_visibility.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

_TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "buddies", "templates", "buddies", "partnership_onboarding.html",
)

_GUARD = "{% if ai_smart_create_available %}"
_ENDGUARD = "{% endif %}"


def _load() -> str:
    with open(_TEMPLATE, encoding="utf-8") as f:
        return f.read()


def _guarded_block_contains(html: str, button_id: str) -> bool:
    """Return True if button_id appears inside a {% if ai_smart_create_available %} block."""
    guard_pos = -1
    search_from = 0
    while True:
        guard_pos = html.find(_GUARD, search_from)
        if guard_pos == -1:
            return False
        end_pos = html.find(_ENDGUARD, guard_pos)
        if end_pos == -1:
            return False
        block = html[guard_pos:end_pos]
        if button_id in block:
            return True
        search_from = end_pos + len(_ENDGUARD)


class TestOnboardingAiButtonVisibility:

    def test_tag_ai_button_is_guarded(self):
        html = _load()
        assert _guarded_block_contains(html, 'id="tag-ai-btn"'), (
            'tag-ai-btn must be inside {% if ai_smart_create_available %}'
        )

    def test_cat_ai_button_is_guarded(self):
        html = _load()
        assert _guarded_block_contains(html, 'id="cat-ai-btn"'), (
            'cat-ai-btn must be inside {% if ai_smart_create_available %}'
        )

    def test_js_listener_uses_optional_chain(self):
        html = _load()
        assert "getElementById('tag-ai-btn')?." in html, (
            "JS addEventListener for tag-ai-btn must use optional chaining (?.) "
            "so it does not throw when the button is absent from the DOM"
        )
        assert "getElementById('cat-ai-btn')?." in html, (
            "JS addEventListener for cat-ai-btn must use optional chaining (?.) "
            "so it does not throw when the button is absent from the DOM"
        )
