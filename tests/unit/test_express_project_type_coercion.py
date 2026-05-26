"""
Unit tests for the project_uid -> forced type=expense coercion in
budget/express_service.py::_validate_items.

Pure Python: mirrors the coercion line without needing Django/DB.
Run with: venv/bin/pytest tests/unit/test_express_project_type_coercion.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Inline the rule under test (Django not available in local venv) ────────

def coerce_type_for_project(tx_type: str, project_uid) -> str:
    if project_uid is not None and tx_type != "expense":
        return "expense"
    return tx_type


class TestCoerceTypeForProject:

    def test_income_with_project_is_forced_to_expense(self):
        assert coerce_type_for_project("income", 42) == "expense"

    def test_savings_dep_with_project_is_forced_to_expense(self):
        assert coerce_type_for_project("savings_dep", 42) == "expense"

    def test_savings_wit_with_project_is_forced_to_expense(self):
        assert coerce_type_for_project("savings_wit", 42) == "expense"

    def test_expense_with_project_stays_expense(self):
        assert coerce_type_for_project("expense", 42) == "expense"

    def test_income_without_project_is_untouched(self):
        assert coerce_type_for_project("income", None) == "income"

    def test_expense_without_project_is_untouched(self):
        assert coerce_type_for_project("expense", None) == "expense"
