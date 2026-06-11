"""
AI-assisted classification for the Unclassified Expenses page: suggests a
category and/or tags for a single expense, picking only from the feuser's own
closed catalog. Talks to the AI exclusively through budget.ai_service.AIService
-- the single shared entry point used by every AI feature (express creation,
dashboard card AI, partnership AI). This module only owns what's specific to
this feature: the system prompt text and the context it's built from.

Like express creation's project/buddy references (budget/express_service.py),
the category and tag catalogs are given to the AI as 0-based "idx" positions
into this request's own list, never as real database uids: the AI can then
only ever point at a position in the list it was actually given, so it can
neither mis-type/hallucinate an id nor reference another feuser's category or
tag, even before solve_unclassified's own bounds-check translates idx back to
a real uid server-side.
"""
from __future__ import annotations

import json

from .unclassified import category_tag_catalog

_SYSTEM_INSTRUCTIONS = """You are a categorization assistant for a budgeting app called Comaney.
You will be given one expense along with the user's own category/tag catalog, and told which of "category" or "tags" (or both) is currently missing for it. Your job is to suggest values ONLY for the field(s) that are missing.

Response format -- your ENTIRE reply, from the very first character to the very last, must be exactly one JSON object and nothing else. The first character of your reply MUST be "{" and the last character MUST be "}": no prose, no markdown, no code fences (no ``` anywhere), no leading text, no trailing note or summary after the closing brace.

{"category_idx": 5, "tag_idxs": [2, 7]}

Rules:
- Only include "category_idx" if category was reported missing below; omit it entirely (or use null) otherwise. Same for "tag_idxs" and tags.
- category_idx must be the integer "idx" of one entry from the Categories list below (never its title, never a uid), or null if nothing in the catalog is a good fit. Never invent a category or guess an idx that isn't in the list.
- tag_idxs must be an array of integer "idx" values from the Tags list below (can be empty). Never invent a tag or guess an idx that isn't in the list.
- This is a CLOSED catalog: you may only choose values that already exist in the lists below, by their idx. If nothing fits well, leave that field null/empty rather than forcing a bad match.
- Base your suggestion on the expense's title, payee, note, value, type, and project (if any). If this is a shared expense and the owner's own classification of it is provided below, use it as a strong hint for finding the equivalent (or a similarly-named) category/tag in the user's own catalog -- but only ever pick from the user's own catalog, never the owner's.
"""


def _build_expense_block(row: dict) -> str:
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


def _idx_catalog_block(label: str, entries: list[dict]) -> str:
    """entries: the uid-keyed catalog list from category_tag_catalog, re-keyed
    to 0-based idx (position in this same list) for the AI -- see module
    docstring for why idx, never the real uid, is what the AI is shown."""
    idx_entries = [{"idx": i, "title": e["title"]} for i, e in enumerate(entries)]
    return f"{label}:\n{json.dumps(idx_entries, ensure_ascii=False)}"


def build_unclassified_system_prompt(feuser, row: dict, categories: list[dict], tags: list[dict]) -> str:
    """
    Assemble the full system prompt for a single unclassified-expense
    AI-solve request: static instructions + the feuser's custom instructions
    (if any) + their category/tag catalog (as idx, see module docstring) +
    this expense's metadata.

    `categories`/`tags` must be the exact same lists solve_unclassified()
    uses afterward to translate the AI's idx response back to a real uid --
    re-querying independently could return a different row order and
    silently point the AI's idx at the wrong category/tag (same failure mode
    express_service._build_catalog's docstring warns about for project/buddy
    idx).
    """
    parts = [
        _SYSTEM_INSTRUCTIONS,
        _idx_catalog_block("Categories", categories),
        _idx_catalog_block("Tags", tags),
        f"Expense:\n{_build_expense_block(row)}",
    ]
    custom = (feuser.ai_custom_instructions or "").strip()
    if custom:
        parts.append(f"User's custom instructions (follow these when assigning categories/tags):\n{custom}")
    return "\n\n".join(parts)


def _resolve_idx(idx, entries: list[dict]) -> dict | None:
    """entries[idx] if idx is a valid in-range integer position, else None
    (covers a missing/null idx, an out-of-range one, or a hallucinated
    non-integer -- all silently ignored the same way express_service's
    _handle_invalid_ai_reference drops a bad idx, since a closed catalog has
    no meaningful "fail" case, just "no good match")."""
    if not isinstance(idx, int) or isinstance(idx, bool):
        return None
    if not (0 <= idx < len(entries)):
        return None
    return entries[idx]


def solve_unclassified(feuser, row: dict) -> dict:
    """
    Ask the AI to fill in whichever of category/tags is missing on `row`
    (a dict from budget.unclassified.get_unclassified_row). Returns
    {"category_uid": int|None, "tag_uids": list[int], "cost_cents": float},
    the category/tags validated against the feuser's own catalog (never
    touching a field that wasn't missing). `cost_cents` is this one call's
    cost (0 if the feuser is off-trial, same meaning as AIService.last_usage
    elsewhere) -- surfaced so the UI can show what each AI action cost.

    Raises budget.ai_service.AIBudgetExceededError/AIInvalidResponseError
    /AIAuthenticationError/AIBillingError/AITransientError.
    """
    from .ai_service import AIService

    categories, tags = category_tag_catalog(feuser)
    system_prompt = build_unclassified_system_prompt(feuser, row, categories, tags)
    service = AIService(feuser)  # raises AIBudgetExceededError up front if blocked/no key
    result = service.prompt_unclassified_solve(system_prompt)

    # Only ever fill in a field that was actually missing -- never let the AI
    # touch a category/tags value the row already had.
    category_uid = None
    if row["category_uid"] is None:
        matched = _resolve_idx(result.get("category_idx"), categories)
        category_uid = matched["uid"] if matched else None

    tag_uids: list[int] = []
    if not row["tag_uids"]:
        for idx in (result.get("tag_idxs") or []):
            matched = _resolve_idx(idx, tags)
            if matched:
                tag_uids.append(matched["uid"])

    cost_cents = (service.last_usage or {}).get("cost_cents", 0)
    return {"category_uid": category_uid, "tag_uids": tag_uids, "cost_cents": cost_cents}


def suggest_tags(
    feuser, *, title: str, type_: str, value: str, payee: str, date_due: str | None,
    note: str, category_uid: int | None = None,
) -> dict:
    """
    AI tag suggestion for the expense/recurring-expense create+edit forms'
    "AI: select tags" button, next to the tag checkbox list. Unlike
    solve_unclassified this never looks up a DB expense or overlay -- the
    form (still being edited, possibly not yet saved) sends its current field
    values directly. category_uid, if the form already has one selected, is
    passed through as context only (it's never suggested or returned here:
    that's the "Category" dropdown's own job, not this button's).

    Always asks the AI for tags, regardless of what's already checked in the
    form -- the button's whole point is to (re)fill the list on demand, unlike
    the Unclassified page's "never touch a field that wasn't missing" rule,
    which only makes sense once something is actually persisted.

    Returns {"tag_uids": list[int], "tag_titles": list[str], "cost_cents": float}.
    Raises the same AIService errors as solve_unclassified.
    """
    row = {
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
    result = solve_unclassified(feuser, row)

    _, tags = category_tag_catalog(feuser)
    tag_map = {t["uid"]: t["title"] for t in tags}
    tag_uids = result["tag_uids"]
    return {
        "tag_uids": tag_uids,
        "tag_titles": [tag_map[u] for u in tag_uids if u in tag_map],
        "cost_cents": result.get("cost_cents", 0),
    }
