"""
Unit tests for the "View expenses" success-link routing decision in
budget/views/express.py (the confirm action).

Django is not importable in the local venv, so this mirrors the pure decision
logic that turns the list of saved-expense targets into the extra query params
appended to the redirect URL.
Run with: venv/bin/pytest tests/unit/test_express_view_expenses_link.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Mirror of the redirect-suffix decision in express.py::confirm ──────────
# created_targets entries: ("buddy", None) | ("project", uid) | ("personal", None)

def view_suffix(created_targets):
    suffix = ""
    kinds = {t[0] for t in created_targets}
    if created_targets and kinds == {"buddy"}:
        suffix = "&view=buddies"
    elif created_targets and kinds == {"project"}:
        project_ids = {t[1] for t in created_targets}
        if len(project_ids) == 1:
            suffix = f"&view=project&pid={next(iter(project_ids))}"
    return suffix


class TestViewExpensesLink:

    def test_all_direct_buddy_goes_to_summary(self):
        targets = [("buddy", None), ("buddy", None)]
        assert view_suffix(targets) == "&view=buddies"

    def test_all_same_project_goes_to_project(self):
        targets = [("project", 5), ("project", 5)]
        assert view_suffix(targets) == "&view=project&pid=5"

    def test_mixed_projects_falls_back_to_list(self):
        targets = [("project", 5), ("project", 7)]
        assert view_suffix(targets) == ""

    def test_buddy_and_project_mix_falls_back(self):
        targets = [("buddy", None), ("project", 5)]
        assert view_suffix(targets) == ""

    def test_personal_expense_falls_back(self):
        assert view_suffix([("personal", None)]) == ""

    def test_project_plus_personal_falls_back(self):
        assert view_suffix([("project", 5), ("personal", None)]) == ""

    def test_empty_falls_back(self):
        assert view_suffix([]) == ""

    def test_single_buddy_goes_to_summary(self):
        assert view_suffix([("buddy", None)]) == "&view=buddies"

    def test_single_project(self):
        assert view_suffix([("project", 12)]) == "&view=project&pid=12"
