"""
Unclassified Expenses page: list, per-row save, bulk save, and AI-solve.

    GET  /budget/unclassified/                  -> unclassified_list
    POST /budget/unclassified/<uid>/save/        -> unclassified_save
    POST /budget/unclassified/<uid>/ai-solve/     -> unclassified_ai_solve
    POST /budget/unclassified/save-all/          -> unclassified_save_all
"""
import json
import logging

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from ..ai_service import (
    AIAuthenticationError,
    AIBillingError,
    AIBudgetExceededError,
    AIInvalidResponseError,
    AIRefusalError,
    AITransientError,
)
from ..decorators import feuser_required
from ..models import Category, Tag
from ..services import upsert_overlay
from ..unclassified import category_tag_catalog, get_unclassified_row, get_unclassified_rows, resolve_expense_kind

_log = logging.getLogger(__name__)


def _ok(data: dict, status: int = 200) -> JsonResponse:
    return JsonResponse(data, status=status)


def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": msg}, status=status)


def _parse_body(request) -> dict:
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}


def _resolve_category_and_tags(feuser, category_uid, tag_uids) -> tuple[Category | None, list[Tag]] | None:
    """Validate that category_uid/tag_uids belong to feuser's own catalog.
    Returns None if any id doesn't -- a security boundary, not just UX."""
    category = None
    if category_uid is not None:
        try:
            category = Category.objects.get(uid=category_uid, owning_feuser=feuser)
        except (Category.DoesNotExist, ValueError, TypeError):
            return None
    tags = []
    if tag_uids:
        if not isinstance(tag_uids, list):
            return None
        tags = list(Tag.objects.filter(uid__in=tag_uids, owning_feuser=feuser))
        if len(tags) != len(set(tag_uids)):
            return None
    return category, tags


def _save_row(feuser, expense_uid, category_uid, tag_uids) -> dict | None:
    """Persist category/tags for expense_uid, own-vs-overlay routed exactly
    like expense_edit/expense_edit_overlay. Returns the refreshed row dict, or
    None if feuser has no access to this expense or the ids are invalid."""
    expense, kind, overlay = resolve_expense_kind(feuser, expense_uid)
    if expense is None:
        return None

    resolved = _resolve_category_and_tags(feuser, category_uid, tag_uids)
    if resolved is None:
        return None
    category, tags = resolved

    if kind == "own":
        expense.category = category
        expense.tags.set(tags)
        expense.save(update_fields=["category"])
    else:
        note = overlay.note if overlay else None
        upsert_overlay(expense, feuser, category, tags, note=note)

    return get_unclassified_row(feuser, expense_uid)


@feuser_required
def unclassified_list(request):
    feuser = request.feuser
    rows = get_unclassified_rows(feuser)
    categories, tags = category_tag_catalog(feuser)
    context = {
        "active_nav": "unclassified",
        "rows_json": json.dumps(rows),
        "categories_json": json.dumps(categories),
        "tags_json": json.dumps(tags),
    }
    return render(request, "budget/unclassified_list.html", context)


@feuser_required
@require_http_methods(["POST"])
def unclassified_save(request, uid: int):
    feuser = request.feuser
    body = _parse_body(request)
    row = _save_row(feuser, uid, body.get("category_uid"), body.get("tag_uids"))
    if row is None:
        return _err("Not found or invalid category/tags", 404)
    return _ok({"row": row})


@feuser_required
@require_http_methods(["POST"])
def unclassified_save_all(request):
    feuser = request.feuser
    body = _parse_body(request)
    entries = body.get("rows")
    if not isinstance(entries, list) or not entries:
        return _err("rows is required")

    results = []
    try:
        with transaction.atomic():
            for entry in entries:
                if not isinstance(entry, dict) or "expense_uid" not in entry:
                    raise ValueError("malformed row entry")
                row = _save_row(
                    feuser, entry["expense_uid"],
                    entry.get("category_uid"), entry.get("tag_uids"),
                )
                if row is None:
                    raise ValueError(f"invalid entry for expense {entry.get('expense_uid')!r}")
                results.append(row)
    except ValueError as exc:
        return _err(str(exc), 400)

    return _ok({"rows": results})


def _call_ai(fn, log_label: str):
    """Run an AIService-backed callable, translating its typed exceptions
    into a JsonResponse. Returns (result, None) on success or (None,
    JsonResponse) on failure -- shared by unclassified_ai_solve and
    expense_ai_suggest_tags so the two don't drift on error handling/status
    codes for the same underlying AIService error types."""
    try:
        return fn(), None
    except AIBudgetExceededError as exc:
        return None, _err(str(exc) or "AI budget exceeded.", 402)
    except AIRefusalError as exc:
        return None, _err(str(exc) or "The AI could not classify this expense.", 400)
    except AIInvalidResponseError:
        return None, _err("The AI returned something unexpected. Please try again.", 400)
    except AIBillingError as exc:
        return None, _err(str(exc) or "AI is temporarily unavailable (out of credits).", 402)
    except AIAuthenticationError as exc:
        return None, _err(str(exc) or "AI is misconfigured. Please contact the administrator.", 500)
    except AITransientError as exc:
        return None, _err(str(exc) or "AI is temporarily unavailable. Please try again.", 503)
    except Exception:
        _log.exception("%s: AI call failed", log_label)
        return None, _err("AI suggestion failed. Please try again.", 500)


@feuser_required
@require_http_methods(["POST"])
def unclassified_ai_solve(request, uid: int):
    from ..unclassified_ai import solve_unclassified

    feuser = request.feuser
    row = get_unclassified_row(feuser, uid)
    if row is None:
        return _err("Not found", 404)
    if row["problem"] is None:
        return _err("This expense is already fully classified.", 400)

    suggestion, error = _call_ai(lambda: solve_unclassified(feuser, row), "unclassified_ai_solve")
    if error:
        return error

    categories, tags = category_tag_catalog(feuser)
    category_map = {c["uid"]: c["title"] for c in categories}
    tag_map = {t["uid"]: t["title"] for t in tags}

    category_uid = suggestion["category_uid"] if row["category_uid"] is None else row["category_uid"]
    tag_uids = suggestion["tag_uids"] if not row["tag_uids"] else row["tag_uids"]

    return _ok({
        "category_uid": category_uid,
        "category_title": category_map.get(category_uid),
        "tag_uids": tag_uids,
        "tag_titles": [tag_map[u] for u in tag_uids if u in tag_map],
        "cost_cents": suggestion.get("cost_cents", 0),
    })


@feuser_required
@require_http_methods(["POST"])
def expense_ai_suggest_tags(request):
    """AI tag suggestion for the expense/recurring-expense create+edit forms'
    "AI: select tags" button. Unlike unclassified_ai_solve this never looks
    up a DB expense: the form (still being edited, possibly not yet created)
    sends its current field values directly, and the response only ever
    covers tags -- see budget.unclassified_ai.suggest_tags for why."""
    from ..unclassified_ai import suggest_tags

    feuser = request.feuser
    body = _parse_body(request)

    category_uid = body.get("category_uid")
    try:
        category_uid = int(category_uid) if category_uid not in (None, "") else None
    except (TypeError, ValueError):
        category_uid = None

    result, error = _call_ai(lambda: suggest_tags(
        feuser,
        title=body.get("title") or "",
        type_=body.get("type") or "",
        value=body.get("value") or "",
        payee=body.get("payee") or "",
        date_due=body.get("date_due") or None,
        note=body.get("note") or "",
        category_uid=category_uid,
    ), "expense_ai_suggest_tags")
    if error:
        return error

    return _ok(result)
