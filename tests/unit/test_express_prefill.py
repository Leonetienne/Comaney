"""
Unit tests for budget/express_prefill.py: the trailing space appended to text
AI Express opens with (e.g. from a project's + button), so the user can keep
typing right away.
Run with: venv/bin/pytest tests/unit/test_express_prefill.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from budget.express_prefill import with_typing_space


class TestWithTypingSpace:
    def test_appends_single_space(self):
        assert with_typing_space("Hello") == "Hello "

    def test_collapses_existing_trailing_whitespace(self):
        assert with_typing_space("Hello  \n") == "Hello "

    def test_empty_stays_empty(self):
        assert with_typing_space("") == ""
        assert with_typing_space("   ") == ""
        assert with_typing_space(None) == ""
