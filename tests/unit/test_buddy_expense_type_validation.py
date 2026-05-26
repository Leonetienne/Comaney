"""
Unit tests for the buddy/project expense type rule: an expense that has a
project, buddy_spendings, or a dummy upfront payer must be type=EXPENSE.

Pure Python — mirrors the condition in budget/expense_factory.py::create_expense
and budget/views/expenses.py::_parse_buddy_post without needing Django/DB.
Run with: venv/bin/pytest tests/unit/test_buddy_expense_type_validation.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Inline the rule under test (Django not available in local venv) ────────

def is_buddy_expense_type_valid(expense_type: str, *, project=None, buddy_spendings=None, is_dummy: bool = False) -> bool:
    is_buddy_expense = bool(project or buddy_spendings or is_dummy)
    if is_buddy_expense and expense_type != "expense":
        return False
    return True


class TestBuddyExpenseTypeValidation:

    def test_personal_income_without_project_is_valid(self):
        assert is_buddy_expense_type_valid("income") is True

    def test_personal_savings_without_project_is_valid(self):
        assert is_buddy_expense_type_valid("savings_dep") is True
        assert is_buddy_expense_type_valid("savings_wit") is True

    def test_project_expense_is_valid(self):
        assert is_buddy_expense_type_valid("expense", project=object()) is True

    def test_project_income_is_invalid(self):
        assert is_buddy_expense_type_valid("income", project=object()) is False

    def test_project_savings_is_invalid(self):
        assert is_buddy_expense_type_valid("savings_dep", project=object()) is False
        assert is_buddy_expense_type_valid("savings_wit", project=object()) is False

    def test_direct_buddy_spendings_income_is_invalid(self):
        assert is_buddy_expense_type_valid("income", buddy_spendings=[{"type": "feuser", "id": 1, "share_percent": 50}]) is False

    def test_direct_buddy_spendings_expense_is_valid(self):
        assert is_buddy_expense_type_valid("expense", buddy_spendings=[{"type": "feuser", "id": 1, "share_percent": 50}]) is True

    def test_empty_buddy_spendings_does_not_trigger_rule(self):
        # An empty list is falsy, so a payer-only expense with no participants
        # yet isn't treated as a buddy expense by this check alone.
        assert is_buddy_expense_type_valid("income", buddy_spendings=[]) is True

    def test_dummy_upfront_payer_income_is_invalid(self):
        assert is_buddy_expense_type_valid("income", is_dummy=True) is False

    def test_dummy_upfront_payer_expense_is_valid(self):
        assert is_buddy_expense_type_valid("expense", is_dummy=True) is True
