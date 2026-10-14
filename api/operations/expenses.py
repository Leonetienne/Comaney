from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from budget import expense_service
from budget.expense_service import ExpenseActionError
from budget.forms import ExpenseForm, ExpenseOverlayForm
from budget.models import Expense, ExpenseDataOverlay
from budget.query_parser import apply_query
from budget.views._sharing import build_shared_qs

from . import confirm
from .common import (
    ASSIGNMENT, DATE, ID, MONEY, PERIOD_PARAMS, SHARING, TYPE, assignment_json, expense_json,
    form_data, form_errors, parse_assignment_arg, resolve_period,
)
from ..registry import READ, WRITE, NotFound, OpError, operation

EXPENSE_FIELDS = {
    "title":                   {"type": "string", "description": "Up to 128 characters."},
    "payee":                   {"type": "string"},
    "type":                    TYPE,
    "value":                   MONEY,
    "category_id":             {"type": ["integer", "null"], "description": "One of the feuser's categories."},
    "tag_ids":                 {"type": "array", "items": {"type": "integer"}, "description": "Replaces all tags."},
    "note":                    {"type": "string", "description": "Up to 1024 characters."},
    "date_due":                DATE,
    "settled":                 {"type": "boolean", "description": "Money has moved. Unsettled needs date_due."},
    "auto_settle_on_due_date": {"type": "boolean"},
    "deactivated":             {"type": "boolean", "description": "Hidden from totals and charts."},
    "notify":                  {"type": "boolean", "description": "Email reminders for this expense."},
    "assignment":              ASSIGNMENT,
}
_RENAMES = {"category_id": "category", "tag_ids": "tags"}
_FORM_FIELDS = ExpenseForm._meta.fields
_QUERY = {"type": "string", "description": (
    "Query language: free text, type=, settled=, deactivated=, value>12, date>=2025-01-01, "
    "cat=, tag=, payee=, project=, uid=<id> or #<id>, || for OR, () grouping, ! for NOT."
)}

LIST_PARAMS = {
    **PERIOD_PARAMS,
    "q": _QUERY,
    "sharing": SHARING,
    "sort_by": {"type": "string", "enum": ["title", "payee", "value", "date"]},
    "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
}


def _rows(feuser, args):
    """(expense, effective_value, is_foreign, overlay) for the period, filter and sharing mode."""
    start, end = resolve_period(feuser, args)
    shared = args.get("sharing") == "shared"
    sort_field = {
        "title": "title", "payee": "payee", "date": "date_due",
        "value": "effective_value" if shared else "value",
    }.get(args.get("sort_by", "date"), "date_due")
    if args.get("sort_dir", "desc") == "desc":
        sort_field = "-" + sort_field

    prefetch = ("tags", "buddy_spendings__participant_feuser", "buddy_spendings__participant_dummy")
    if shared:
        qs = build_shared_qs(feuser, start, end).select_related(
            "category", "project", "owning_feuser", "upfront_payee_dummy",
        )
    else:
        qs = Expense.objects.filter(
            owning_feuser=feuser, is_dummy=False, date_due__gte=start, date_due__lte=end,
        ).select_related("category", "project", "owning_feuser", "upfront_payee_dummy")
    qs = apply_query(qs.prefetch_related(*prefetch).order_by(sort_field, "date_created"), args.get("q", ""), feuser=feuser)
    expenses = list(qs)

    overlays = {}
    foreign_ids = [e.uid for e in expenses if e.owning_feuser_id != feuser.pk]
    if foreign_ids:
        overlays = {
            ov.expense_id: ov
            for ov in ExpenseDataOverlay.objects.filter(expense_id__in=foreign_ids, feuser=feuser)
            .select_related("category").prefetch_related("tags")
        }
    return [
        (e, getattr(e, "effective_value", None), e.owning_feuser_id != feuser.pk, overlays.get(e.uid))
        for e in expenses
    ]


@operation(
    "expenses_list", concern="expenses", access=READ, method="GET", path="expenses/",
    description="List expenses in a period (default: current financial month), optionally filtered by a query.",
    params=LIST_PARAMS,
)
def expenses_list(ctx, args):
    return {"expenses": [expense_json(e, ev, foreign, ov) for e, ev, foreign, ov in _rows(ctx.feuser, args)]}


@operation(
    "expenses_totals", concern="expenses", access=READ, method="GET", path="expenses/totals/",
    description=(
        "Sum expenses of one type in a period, optionally filtered by a query and grouped. "
        "In shared mode foreign and shared expenses count at the feuser's own share."
    ),
    params={
        **LIST_PARAMS,
        "type": {**TYPE, "description": "Transaction type to sum (default expense)."},
        "group_by": {"type": "string", "enum": ["none", "category", "tag", "payee", "month"]},
    },
)
def expenses_totals(ctx, args):
    feuser = ctx.feuser
    start, end = resolve_period(feuser, args)
    wanted_type = args.get("type", "expense")
    group_by = args.get("group_by", "none")
    total = Decimal("0")
    count = 0
    groups = defaultdict(lambda: [Decimal("0"), 0])
    for exp, effective, foreign, overlay in _rows(feuser, args):
        if exp.type != wanted_type or exp.deactivated:
            continue
        amount = effective if effective is not None else exp.value
        total += amount
        count += 1
        if group_by == "none":
            continue
        if group_by == "payee":
            keys = [exp.payee or ""]
        elif group_by == "month":
            keys = [exp.date_due.strftime("%Y-%m") if exp.date_due else ""]
        elif group_by == "category":
            cat = (overlay.category if overlay else None) if foreign else exp.category
            keys = [cat.title if cat else ""]
        else:
            tags = (list(overlay.tags.all()) if overlay else []) if foreign else list(exp.tags.all())
            keys = [t.title for t in tags] or [""]
        for key in keys:
            groups[key][0] += amount
            groups[key][1] += 1
    result = {
        "currency": feuser.currency,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "type": wanted_type,
        "total": str(total.quantize(Decimal("0.01"))),
        "count": count,
    }
    if group_by != "none":
        result["group_by"] = group_by
        result["groups"] = sorted(
            ({"key": k, "total": str(v[0].quantize(Decimal("0.01"))), "count": v[1]} for k, v in groups.items()),
            key=lambda g: Decimal(g["total"]), reverse=True,
        )
        if group_by == "tag":
            result["note"] = "An expense with several tags counts in each of their groups."
    return result


def _visible_expense(feuser, uid):
    """(expense, effective_value, is_foreign, overlay) for an expense feuser owns, administers or shares."""
    exp = build_shared_qs(feuser, None, None).filter(uid=uid).first()
    if exp is None:
        try:
            exp, _admin = expense_service.editable_expense(feuser, uid)
        except (Expense.DoesNotExist, ExpenseActionError):
            exp = Expense.objects.filter(uid=uid, owning_feuser=feuser).first()
        if exp is None:
            raise NotFound("Expense not found.")
        return exp, None, False, None
    foreign = exp.owning_feuser_id != feuser.pk
    overlay = ExpenseDataOverlay.objects.filter(expense=exp, feuser=feuser).first() if foreign else None
    return exp, exp.effective_value, foreign, overlay


def _detail_json(feuser, uid):
    exp, effective, foreign, overlay = _visible_expense(feuser, uid)
    data = expense_json(exp, effective, foreign, overlay)
    if not foreign:
        data["assignment"] = assignment_json(exp, feuser)
    return data


@operation(
    "expenses_get", concern="expenses", access=READ, method="GET", path="expenses/<int:id>/",
    description="One expense the feuser owns, administers as project admin, or participates in.",
    params={"id": ID}, required=["id"],
)
def expenses_get(ctx, args):
    return _detail_json(ctx.feuser, args["id"])


def _changes(args):
    return {k: v for k, v in args.items() if k in EXPENSE_FIELDS and k != "assignment"}


@operation(
    "expenses_create", concern="expenses", access=WRITE, method="POST", path="expenses/",
    description=(
        "Create an expense (default settled, due today). With an assignment it is shared; "
        "participants and payers are notified like in the web app."
    ),
    params=EXPENSE_FIELDS, required=["title", "type", "value"], status=201,
)
def expenses_create(ctx, args):
    feuser = ctx.feuser
    defaults = {"settled": True, "notify": True, "date_due": timezone.localdate().isoformat()}
    form = ExpenseForm(form_data(None, _FORM_FIELDS, {**defaults, **_changes(args)}, _RENAMES), feuser=feuser)
    if not form.is_valid():
        raise form_errors(form, _RENAMES)
    buddy = parse_assignment_arg(feuser, args["assignment"], form.cleaned_data["type"]) if args.get("assignment") else None
    expense = expense_service.save_new_expense(feuser, form.save(commit=False), form.cleaned_data["tags"], buddy)
    if expense.owning_feuser_id != feuser.pk:
        return {**expense_json(expense), "note_for_caller": "Another feuser paid upfront, so the expense now belongs to them and awaits their approval."}
    return _detail_json(feuser, expense.uid)


@operation(
    "expenses_update", concern="expenses", access=WRITE, method="PATCH", path="expenses/<int:id>/",
    description=(
        "Change an own expense; only given fields change. assignment replaces the sharing "
        "(null makes it personal). Changing title, value, participants or shares resets participant approvals."
    ),
    params={"id": ID, **EXPENSE_FIELDS}, required=["id"],
)
def expenses_update(ctx, args):
    feuser = ctx.feuser
    try:
        expense, is_admin_edit = expense_service.editable_expense(feuser, args["id"])
    except Expense.DoesNotExist:
        raise NotFound("Expense not found.")
    except ExpenseActionError as exc:
        raise OpError(str(exc), 403)
    form_feuser = expense.owning_feuser if is_admin_edit else feuser
    form = ExpenseForm(form_data(expense, _FORM_FIELDS, _changes(args), _RENAMES), instance=expense, feuser=form_feuser)
    if not form.is_valid():
        raise form_errors(form, _RENAMES)
    if "assignment" in args:
        buddy = parse_assignment_arg(feuser, args["assignment"], form.cleaned_data["type"])
    else:
        buddy = expense_service.KEEP_ASSIGNMENT
        if form.cleaned_data["type"] != "expense" and expense_service.current_assignment(expense, feuser):
            raise OpError(expense_service.BUDDY_TYPE_CONFLICT_MSG)
    moved = expense_service.update_expense(feuser, expense, form.save, buddy, is_admin_edit=is_admin_edit)
    if moved:
        return {"id": expense.uid, "note_for_caller": "The new upfront payer now owns this expense and must approve it."}
    return _detail_json(feuser, expense.uid)


@operation(
    "expenses_delete", concern="expenses", access=WRITE, method="DELETE", path="expenses/<int:id>/",
    description="Delete one own expense. Confirmed settlements cannot be deleted.",
    params={"id": ID}, required=["id"], destructive=True, status=204,
)
def expenses_delete(ctx, args):
    expense = Expense.objects.filter(uid=args["id"], owning_feuser=ctx.feuser).first()
    if expense is None:
        raise NotFound("Expense not found.")
    try:
        expense_service.delete_expense(ctx.feuser, expense)
    except ExpenseActionError as exc:
        raise OpError(str(exc), 403)
    return None


@operation(
    "expenses_clone", concern="expenses", access=WRITE, method="POST", path="expenses/<int:id>/clone/",
    description="Copy an own expense, participants included, as \"CLONE - <title>\".",
    params={"id": ID}, required=["id"], status=201,
)
def expenses_clone(ctx, args):
    expense = Expense.objects.filter(uid=args["id"], owning_feuser=ctx.feuser).first()
    if expense is None:
        raise NotFound("Expense not found.")
    try:
        clone = expense_service.clone_expense(ctx.feuser, expense)
    except ExpenseActionError as exc:
        raise OpError(str(exc), 403)
    return _detail_json(ctx.feuser, clone.uid)


def _overlay_json(feuser, expense):
    overlay = ExpenseDataOverlay.objects.filter(expense=expense, feuser=feuser).first()
    return {
        "expense_id": expense.uid,
        "category": {"id": overlay.category.uid, "title": overlay.category.title} if overlay and overlay.category else None,
        "tags": [{"id": t.uid, "title": t.title} for t in overlay.tags.all()] if overlay else [],
        "note": (overlay.note or "") if overlay else "",
    }


def _participant_expense(feuser, uid):
    try:
        return expense_service.participant_expense(feuser, uid)
    except Expense.DoesNotExist:
        raise NotFound("No foreign expense with this id that the feuser participates in.")


@operation(
    "expenses_overlay_get", concern="expenses", access=READ, method="GET", path="expenses/<int:id>/overlay/",
    description="The feuser's own category, tags and note on a foreign expense they participate in.",
    params={"id": ID}, required=["id"],
)
def expenses_overlay_get(ctx, args):
    return _overlay_json(ctx.feuser, _participant_expense(ctx.feuser, args["id"]))


@operation(
    "expenses_overlay_set", concern="expenses", access=WRITE, method="PUT", path="expenses/<int:id>/overlay/",
    description=(
        "Set the feuser's own category, tags and note on a foreign expense; the owner's "
        "classification is untouched. Omitted fields are cleared."
    ),
    params={
        "id": ID,
        "category_id": EXPENSE_FIELDS["category_id"],
        "tag_ids": EXPENSE_FIELDS["tag_ids"],
        "note": EXPENSE_FIELDS["note"],
    },
    required=["id"],
)
def expenses_overlay_set(ctx, args):
    feuser = ctx.feuser
    expense = _participant_expense(feuser, args["id"])
    data = {"category": args.get("category_id") or "", "tags": args.get("tag_ids") or [], "note": args.get("note", "")}
    form = ExpenseOverlayForm(data, feuser=feuser)
    if not form.is_valid():
        raise form_errors(form, _RENAMES)
    expense_service.set_overlay(feuser, expense, form.cleaned_data["category"], form.cleaned_data["tags"], form.cleaned_data["note"])
    return _overlay_json(feuser, expense)


def _deletable(feuser, ids):
    return list(
        Expense.objects.filter(owning_feuser=feuser, uid__in=ids, is_dummy=False, is_buddies_settlement=False)
        .order_by("uid")
    )


@operation(
    "expenses_bulk", concern="expenses", access=WRITE, method="POST", path="expenses/bulk/",
    description=(
        "Apply one action to many expenses. Tag and category actions on foreign expenses change the "
        "feuser's own overlay. delete is two-step: without confirm_token nothing is deleted and the "
        "matching expenses plus a confirm_token (10 minutes) come back; repeat the call with that token "
        "to delete exactly those. Settlements are never bulk deleted."
    ),
    params={
        "action": {"type": "string", "enum": list(expense_service.BULK_ACTIONS)},
        "ids": {"type": "array", "items": {"type": "integer"}},
        "tag_id": {"type": "integer", "description": "For add-tag and remove-tag."},
        "category_id": {"type": ["integer", "null"], "description": "For set-category; null clears."},
        "confirm_token": {"type": "string", "description": "From the delete preview."},
    },
    required=["action", "ids"], destructive=True,
)
def expenses_bulk(ctx, args):
    feuser = ctx.feuser
    ids = sorted({int(i) for i in args["ids"]})
    if not ids:
        raise OpError("'ids' must not be empty.")
    if args["action"] == "delete":
        rows = _deletable(feuser, ids)
        state = confirm.fingerprint([(e.uid, e.last_mod.isoformat()) for e in rows])
        if not args.get("confirm_token"):
            total = sum((e.value for e in rows), Decimal("0"))
            return {
                "preview": True,
                "deletes": [{"id": e.uid, "title": e.title, "value": str(e.value), "date_due": e.date_due.isoformat() if e.date_due else None} for e in rows],
                "count": len(rows),
                "total": str(total),
                "skipped_ids": [i for i in ids if i not in {e.uid for e in rows}],
                "confirm_token": confirm.issue(ctx, "expenses_bulk_delete", state),
            }
        confirm.check(ctx, args["confirm_token"], "expenses_bulk_delete", state)
    try:
        result = expense_service.bulk_action(
            feuser, args["action"], ids, tag_uid=args.get("tag_id"), category_uid=args.get("category_id"),
        )
    except ExpenseActionError as exc:
        raise OpError(str(exc))
    return {"updated": result.updated, "foreign": result.foreign, "updated_via_overlay": result.via_overlay}

