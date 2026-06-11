"""
AI-assisted classification for the Unclassified Expenses page: suggests a
category and/or tags for a single expense, picking only from the feuser's own
closed catalog. Talks to the AI exclusively through budget.ai_service.AIService
-- the single shared entry point used by every AI feature (express creation,
dashboard card AI, partnership AI). This module only owns what's specific to
this feature: the system prompt text and the context it's built from.
"""
from __future__ import annotations

import json

from .unclassified import category_tag_catalog

_SYSTEM_INSTRUCTIONS = """You are a categorization assistant for a budgeting app called Comaney.
You will be given one expense along with the user's own category/tag catalog, and told which of "category" or "tags" (or both) is currently missing for it. Your job is to suggest values ONLY for the field(s) that are missing.

Response format -- your ENTIRE reply, from the very first character to the very last, must be exactly one JSON object and nothing else. The first character of your reply MUST be "{" and the last character MUST be "}": no prose, no markdown, no code fences (no ``` anywhere), no leading text, no trailing note or summary after the closing brace.

{"category_uid": 5, "tag_uids": [2, 7]}

Rules:
- Only include "category_uid" if category was reported missing below; omit it entirely (or use null) otherwise. Same for "tag_uids" and tags.
- category_uid must be one of the integer uids from the Categories list below, or null if nothing in the catalog is a good fit. Never invent a category.
- tag_uids must be an array of integer uids from the Tags list below (can be empty). Never invent a tag.
- This is a CLOSED catalog: you may only choose values that already exist in the lists below. If nothing fits well, leave that field null/empty rather than forcing a bad match.
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


def build_unclassified_system_prompt(feuser, row: dict) -> str:
    """Assemble the full system prompt for a single unclassified-expense
    AI-solve request: static instructions + the feuser's custom instructions
    (if any) + their category/tag catalog + this expense's metadata."""
    categories, tags = category_tag_catalog(feuser)
    parts = [
        _SYSTEM_INSTRUCTIONS,
        f"Categories:\n{json.dumps(categories, ensure_ascii=False)}",
        f"Tags:\n{json.dumps(tags, ensure_ascii=False)}",
        f"Expense:\n{_build_expense_block(row)}",
    ]
    custom = (feuser.ai_custom_instructions or "").strip()
    if custom:
        parts.append(f"User's custom instructions (follow these when assigning categories/tags):\n{custom}")
    return "\n\n".join(parts)


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

    system_prompt = build_unclassified_system_prompt(feuser, row)
    service = AIService(feuser)  # raises AIBudgetExceededError up front if blocked/no key
    result = service.prompt_unclassified_solve(system_prompt)

    categories, tags = category_tag_catalog(feuser)
    valid_category_uids = {c["uid"] for c in categories}
    valid_tag_uids = {t["uid"] for t in tags}

    # Only ever fill in a field that was actually missing -- never let the AI
    # touch a category/tags value the row already had.
    category_uid = result.get("category_uid")
    if row["category_uid"] is not None or category_uid not in valid_category_uids:
        category_uid = None

    tag_uids: list[int] = []
    if not row["tag_uids"]:
        tag_uids = [u for u in (result.get("tag_uids") or []) if u in valid_tag_uids]

    cost_cents = (service.last_usage or {}).get("cost_cents", 0)
    return {"category_uid": category_uid, "tag_uids": tag_uids, "cost_cents": cost_cents}
