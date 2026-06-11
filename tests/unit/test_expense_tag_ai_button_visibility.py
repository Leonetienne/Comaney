"""
Verify the expense and recurring-expense create+edit forms guard the "AI:
select tags" button behind {% if ai_smart_create_available %}, same pattern
as tests/unit/test_onboarding_ai_button_visibility.py for the partnership
onboarding wizard's AI buttons.

No Django required: we inspect the template source directly.

Run with: venv/bin/pytest tests/unit/test_expense_tag_ai_button_visibility.py -v
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_TEMPLATES = {
    "expense_form": os.path.join(_ROOT, "budget", "templates", "budget", "expense_form.html"),
    "scheduled_form": os.path.join(_ROOT, "budget", "templates", "budget", "scheduled_form.html"),
}

_GUARD = "{% if ai_smart_create_available %}"
_ENDGUARD = "{% endif %}"


def _load(name: str) -> str:
    with open(_TEMPLATES[name], encoding="utf-8") as f:
        return f.read()


def _guarded_block_contains(html: str, needle: str) -> bool:
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
        if needle in block:
            return True
        search_from = end_pos + len(_ENDGUARD)


class TestExpenseFormTagAiButtonVisibility:

    def test_tag_ai_button_is_guarded(self):
        html = _load("expense_form")
        assert _guarded_block_contains(html, 'id="tag-ai-btn"'), (
            'tag-ai-btn must be inside {% if ai_smart_create_available %}'
        )

    def test_script_include_present(self):
        html = _load("expense_form")
        assert "dist/expense_tag_ai.js" in html


class TestScheduledFormTagAiButtonVisibility:

    def test_tag_ai_button_is_guarded(self):
        html = _load("scheduled_form")
        assert _guarded_block_contains(html, 'id="tag-ai-btn"'), (
            'tag-ai-btn must be inside {% if ai_smart_create_available %}'
        )

    def test_script_include_present(self):
        html = _load("scheduled_form")
        assert "dist/expense_tag_ai.js" in html
