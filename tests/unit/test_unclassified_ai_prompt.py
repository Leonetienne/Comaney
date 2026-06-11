"""
Unit tests for the unclassified-expense AI prompt assembly
(budget/unclassified_ai.py) and the "only fill missing fields" merge rule
in budget/unclassified_ai.py::solve_unclassified.

Django is not needed for these pure functions, so (as with
test_dashboard_card_ai_parsing.py / test_express_smart_create_blocks.py)
this mirrors the algorithms directly rather than importing the real module,
which pulls in Django models via budget.unclassified.
Run with: venv/bin/pytest tests/unit/test_unclassified_ai_prompt.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Mirror of budget/unclassified_ai.py::_build_expense_block ──────────────

def build_expense_block(row: dict) -> str:
    parts = [
        f"Title: {row['title']}",
        f"Type: {row['type']}",
        f"Value: {row['value']}",
        f"Payee: {row['payee'] or '(none)'}",
        f"Date due: {row['date_due'] or '(none)'}",
        f"Note: {row['note'] or '(none)'}",
        f"Project: {row['project_title'] or '(none)'}",
    ]
    missing = []
    if row["category_uid"] is None:
        missing.append("category")
    if not row["tag_uids"]:
        missing.append("tags")
    parts.append(f"Missing: {', '.join(missing)}")

    if row["kind"] == "foreign":
        parts.append(
            "This is a shared expense owned by someone else. Their own classification "
            f"of it (context only, not something you can pick from) -- "
            f"category: {row['owner_category_title'] or '(none)'}, "
            f"tags: {', '.join(row['owner_tag_titles']) if row['owner_tag_titles'] else '(none)'}"
        )
    return "\n".join(parts)


# ── Mirror of budget/unclassified_ai.py::solve_unclassified's merge rule ──
# (the "never touch a field that wasn't missing" validation, isolated from
# the AIService network call so it's testable without Django/network)

def merge_ai_result(row: dict, ai_result: dict, valid_category_uids: set, valid_tag_uids: set) -> dict:
    category_uid = ai_result.get("category_uid")
    if row["category_uid"] is not None or category_uid not in valid_category_uids:
        category_uid = None

    tag_uids: list = []
    if not row["tag_uids"]:
        tag_uids = [u for u in (ai_result.get("tag_uids") or []) if u in valid_tag_uids]

    return {"category_uid": category_uid, "tag_uids": tag_uids}


def _base_row(**overrides) -> dict:
    row = {
        "expense_uid": 1,
        "kind": "own",
        "title": "Coffee",
        "value": "3.50",
        "type": "expense",
        "payee": "Starbucks",
        "note": "",
        "date_due": None,
        "project_title": None,
        "category_uid": None,
        "category_title": None,
        "tag_uids": [],
        "tag_titles": [],
        "problem": "Category and Tags missing",
        "owner_category_title": None,
        "owner_tag_titles": None,
    }
    row.update(overrides)
    return row


class TestBuildExpenseBlock:

    def test_includes_core_metadata(self):
        block = build_expense_block(_base_row())
        assert "Title: Coffee" in block
        assert "Payee: Starbucks" in block
        assert "Type: expense" in block

    def test_missing_both_lists_both(self):
        block = build_expense_block(_base_row())
        assert "Missing: category, tags" in block

    def test_missing_category_only(self):
        row = _base_row(category_uid=None, tag_uids=[5], tag_titles=["Food"])
        block = build_expense_block(row)
        assert "Missing: category" in block
        assert "tags" not in block.split("Missing: ")[1].split("\n")[0]

    def test_missing_tags_only(self):
        row = _base_row(category_uid=7, category_title="Bills", tag_uids=[], tag_titles=[])
        block = build_expense_block(row)
        assert block.split("Missing: ")[1].split("\n")[0].strip() == "tags"

    def test_own_expense_has_no_owner_hint(self):
        block = build_expense_block(_base_row(kind="own"))
        assert "shared expense" not in block

    def test_foreign_expense_includes_owner_hint(self):
        row = _base_row(
            kind="foreign",
            owner_category_title="Groceries",
            owner_tag_titles=["Weekly", "Supermarket"],
        )
        block = build_expense_block(row)
        assert "shared expense" in block
        assert "category: Groceries" in block
        assert "tags: Weekly, Supermarket" in block

    def test_foreign_expense_with_no_owner_classification(self):
        row = _base_row(kind="foreign", owner_category_title=None, owner_tag_titles=[])
        block = build_expense_block(row)
        assert "category: (none)" in block
        assert "tags: (none)" in block


class TestMergeAiResult:

    def test_fills_both_when_both_missing(self):
        row = _base_row(category_uid=None, tag_uids=[])
        result = merge_ai_result(row, {"category_uid": 5, "tag_uids": [1, 2]}, {5}, {1, 2, 3})
        assert result == {"category_uid": 5, "tag_uids": [1, 2]}

    def test_never_overwrites_existing_category(self):
        row = _base_row(category_uid=9, tag_uids=[])
        result = merge_ai_result(row, {"category_uid": 5, "tag_uids": []}, {5, 9}, set())
        assert result["category_uid"] is None

    def test_never_overwrites_existing_tags(self):
        row = _base_row(category_uid=None, tag_uids=[1])
        result = merge_ai_result(row, {"category_uid": None, "tag_uids": [2, 3]}, set(), {1, 2, 3})
        assert result["tag_uids"] == []

    def test_invalid_category_uid_dropped(self):
        row = _base_row(category_uid=None, tag_uids=[])
        result = merge_ai_result(row, {"category_uid": 999, "tag_uids": []}, {5}, set())
        assert result["category_uid"] is None

    def test_invalid_tag_uids_filtered_out(self):
        row = _base_row(category_uid=1, tag_uids=[])
        result = merge_ai_result(row, {"category_uid": None, "tag_uids": [1, 999]}, set(), {1})
        assert result["tag_uids"] == [1]

    def test_no_match_found_returns_empty(self):
        row = _base_row(category_uid=None, tag_uids=[])
        result = merge_ai_result(row, {"category_uid": None, "tag_uids": []}, {5}, {1})
        assert result == {"category_uid": None, "tag_uids": []}
