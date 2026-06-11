"""
Unit tests for the unclassified-expense AI prompt assembly
(budget/unclassified_ai.py), the "only fill missing fields" merge rule in
budget/unclassified_ai.py::solve_unclassified, and the row budget/unclassified_ai.py
::suggest_tags builds for the expense/recurring-expense forms' "AI: select
tags" button.

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


# ── Mirror of budget/unclassified_ai.py::_resolve_idx + solve_unclassified's
# merge rule (idx-bounds-checked translation back to a real uid, plus the
# "never touch a field that wasn't missing" validation), isolated from the
# AIService network call so it's testable without Django/network. The AI is
# given categories/tags as 0-based idx positions (never real uids) so it can
# neither mis-type an id nor reference another feuser's category/tag -- same
# reasoning as express creation's project/buddy idx.

def resolve_idx(idx, entries: list[dict]) -> dict | None:
    if not isinstance(idx, int) or isinstance(idx, bool):
        return None
    if not (0 <= idx < len(entries)):
        return None
    return entries[idx]


def merge_ai_result(row: dict, ai_result: dict, categories: list[dict], tags: list[dict]) -> dict:
    category_uid = None
    if row["category_uid"] is None:
        matched = resolve_idx(ai_result.get("category_idx"), categories)
        category_uid = matched["uid"] if matched else None

    tag_uids: list = []
    if not row["tag_uids"]:
        for idx in (ai_result.get("tag_idxs") or []):
            matched = resolve_idx(idx, tags)
            if matched:
                tag_uids.append(matched["uid"])

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


_CATEGORIES = [{"uid": 50, "title": "Food"}, {"uid": 51, "title": "Bills"}]
_TAGS = [{"uid": 90, "title": "Recurring"}, {"uid": 91, "title": "Work"}, {"uid": 92, "title": "Amazon"}]


class TestResolveIdx:

    def test_valid_idx_resolves(self):
        assert resolve_idx(1, _CATEGORIES) == {"uid": 51, "title": "Bills"}

    def test_none_idx_rejected(self):
        assert resolve_idx(None, _CATEGORIES) is None

    def test_out_of_range_idx_rejected(self):
        assert resolve_idx(2, _CATEGORIES) is None

    def test_negative_idx_rejected(self):
        assert resolve_idx(-1, _CATEGORIES) is None

    def test_non_integer_idx_rejected(self):
        assert resolve_idx("1", _CATEGORIES) is None

    def test_bool_idx_rejected(self):
        # bool is a subclass of int in Python; True/False must not be
        # accepted as 1/0 positions.
        assert resolve_idx(True, _CATEGORIES) is None


class TestMergeAiResult:

    def test_fills_both_when_both_missing(self):
        row = _base_row(category_uid=None, tag_uids=[])
        result = merge_ai_result(row, {"category_idx": 1, "tag_idxs": [0, 2]}, _CATEGORIES, _TAGS)
        assert result == {"category_uid": 51, "tag_uids": [90, 92]}

    def test_never_overwrites_existing_category(self):
        row = _base_row(category_uid=9, tag_uids=[])
        result = merge_ai_result(row, {"category_idx": 0, "tag_idxs": []}, _CATEGORIES, _TAGS)
        assert result["category_uid"] is None

    def test_never_overwrites_existing_tags(self):
        row = _base_row(category_uid=None, tag_uids=[90])
        result = merge_ai_result(row, {"category_idx": None, "tag_idxs": [1, 2]}, _CATEGORIES, _TAGS)
        assert result["tag_uids"] == []

    def test_invalid_category_idx_dropped(self):
        row = _base_row(category_uid=None, tag_uids=[])
        result = merge_ai_result(row, {"category_idx": 99, "tag_idxs": []}, _CATEGORIES, _TAGS)
        assert result["category_uid"] is None

    def test_invalid_tag_idx_filtered_out(self):
        row = _base_row(category_uid=1, tag_uids=[])
        result = merge_ai_result(row, {"category_idx": None, "tag_idxs": [0, 99]}, _CATEGORIES, _TAGS)
        assert result["tag_uids"] == [90]

    def test_no_match_found_returns_empty(self):
        row = _base_row(category_uid=None, tag_uids=[])
        result = merge_ai_result(row, {"category_idx": None, "tag_idxs": []}, _CATEGORIES, _TAGS)
        assert result == {"category_uid": None, "tag_uids": []}


# ── Mirror of budget/unclassified_ai.py::suggest_tags's row-building ───────
# (the expense/recurring-expense forms' "AI: select tags" button always asks
# for fresh tags regardless of what's already checked, unlike the
# Unclassified page's "never touch a field that wasn't missing" rule)

def build_suggest_tags_row(*, title, type_, value, payee, date_due, note, category_uid=None) -> dict:
    return {
        "kind": "own",
        "title": title,
        "type": type_,
        "value": value,
        "payee": payee,
        "date_due": date_due,
        "note": note,
        "project_title": None,
        "category_uid": category_uid,
        "tag_uids": [],
        "owner_category_title": None,
        "owner_tag_titles": None,
    }


class TestBuildSuggestTagsRow:

    def test_tags_always_forced_missing(self):
        row = build_suggest_tags_row(title="Coffee", type_="expense", value="3.50", payee="", date_due=None, note="")
        assert row["tag_uids"] == []

    def test_category_uid_passed_through_as_context_only(self):
        row = build_suggest_tags_row(title="Coffee", type_="expense", value="3.50", payee="", date_due=None, note="", category_uid=7)
        assert row["category_uid"] == 7

    def test_own_kind_never_shows_owner_hint(self):
        row = build_suggest_tags_row(title="Coffee", type_="expense", value="3.50", payee="", date_due=None, note="")
        assert "shared expense" not in build_expense_block(row)

    def test_missing_list_is_tags_only_when_category_selected(self):
        row = build_suggest_tags_row(title="Coffee", type_="expense", value="3.50", payee="", date_due=None, note="", category_uid=5)
        missing = build_expense_block(row).split("Missing: ")[1].split("\n")[0]
        assert missing.strip() == "tags"

    def test_missing_list_includes_both_when_no_category_selected(self):
        row = build_suggest_tags_row(title="Coffee", type_="expense", value="3.50", payee="", date_due=None, note="")
        assert "Missing: category, tags" in build_expense_block(row)

    def test_selected_category_uid_never_returned_by_merge(self):
        # Even though a category was passed through as context, the button
        # only ever surfaces tag_uids -- the merge rule independently makes
        # sure an already-set category_uid is never overwritten.
        row = build_suggest_tags_row(title="Coffee", type_="expense", value="3.50", payee="", date_due=None, note="", category_uid=51)
        result = merge_ai_result(row, {"category_idx": 0, "tag_idxs": [1]}, _CATEGORIES, _TAGS)
        assert result["category_uid"] is None
        assert result["tag_uids"] == [91]
