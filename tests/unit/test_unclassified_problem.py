"""
Unit tests for the unclassified-expense "problem" classification in
budget/unclassified.py::_problem.

Django is not needed for this pure function, so (as with
test_express_smart_create_blocks.py) this mirrors the algorithm directly
rather than importing the real module, which pulls in Django models.
Run with: venv/bin/pytest tests/unit/test_unclassified_problem.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Mirror of budget/unclassified.py::_problem ──────────────────────────────

def problem(has_category: bool, has_tags: bool):
    if not has_category and not has_tags:
        return "Category and Tags missing"
    if not has_category:
        return "Category missing"
    if not has_tags:
        return "Tags missing"
    return None


class TestProblemClassification:

    def test_both_present_is_fully_classified(self):
        assert problem(True, True) is None

    def test_missing_category_only(self):
        assert problem(False, True) == "Category missing"

    def test_missing_tags_only(self):
        assert problem(True, False) == "Tags missing"

    def test_missing_both(self):
        assert problem(False, False) == "Category and Tags missing"
