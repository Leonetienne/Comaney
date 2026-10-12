"""
Unit tests for budget/express_prefill.py: the text AI Express opens with when
started from a project's + button (base prompt, project AI preprompt, and the
trailing space that lets the user keep typing right away).
Run with: venv/bin/pytest tests/unit/test_express_prefill.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from budget.express_prefill import project_prefill, with_typing_space


class TestProjectPrefill:
    def test_without_preprompt_is_base_prompt(self):
        assert project_prefill("Trip") == "Create all expenses for project 'Trip'"

    def test_blank_preprompt_is_ignored(self):
        assert project_prefill("Trip", "   \n") == "Create all expenses for project 'Trip'"

    def test_preprompt_follows_base_prompt(self):
        assert project_prefill("Trip", "Put Robert and Mallory always at 0%, they're invited.") == (
            "Create all expenses for project 'Trip'. "
            "Put Robert and Mallory always at 0%, they're invited."
        )

    def test_preprompt_is_stripped(self):
        assert project_prefill("Trip", "  Split evenly.\n") == "Create all expenses for project 'Trip'. Split evenly."


class TestWithTypingSpace:
    def test_appends_single_space(self):
        assert with_typing_space("Hello") == "Hello "

    def test_collapses_existing_trailing_whitespace(self):
        assert with_typing_space("Hello  \n") == "Hello "

    def test_empty_stays_empty(self):
        assert with_typing_space("") == ""
        assert with_typing_space("   ") == ""
        assert with_typing_space(None) == ""
