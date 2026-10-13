from budget import scheduled_service
from budget.forms import ScheduledExpenseForm
from budget.models import ScheduledExpense

from .common import ASSIGNMENT, DATE, ID, MONEY, TYPE, form_data, form_errors, parse_assignment_arg, scheduled_json
from ..registry import READ, WRITE, NotFound, OpError, operation

SCHEDULED_FIELDS = {
    "title":                           {"type": "string"},
    "payee":                           {"type": "string"},
    "type":                            TYPE,
    "value":                           MONEY,
    "repeat_every_factor":             {"type": "integer", "description": "Repeat every N units."},
    "repeat_every_unit":               {"type": "string", "enum": ["days", "weeks", "months", "years"]},
    "repeat_base_date":                {**DATE, "description": "First occurrence."},
    "end_on":                          {**DATE, "description": "Last possible occurrence; null repeats forever."},
    "category_id":                     {"type": ["integer", "null"]},
    "tag_ids":                         {"type": "array", "items": {"type": "integer"}},
    "note":                            {"type": "string"},
    "default_auto_settle_on_due_date": {"type": "boolean"},
    "deactivated":                     {"type": "boolean"},
    "notify":                          {"type": "boolean"},
    "assignment":                      ASSIGNMENT,
}
_RENAMES = {"category_id": "category", "tag_ids": "tags"}
_FORM_FIELDS = ScheduledExpenseForm._meta.fields


def _get(feuser, uid):
    obj = ScheduledExpense.objects.filter(uid=uid, owning_feuser=feuser).first()
    if obj is None:
        raise NotFound("Recurring expense not found.")
    return obj


def _changes(args):
    return {k: v for k, v in args.items() if k in SCHEDULED_FIELDS and k != "assignment"}


@operation(
    "scheduled_list", concern="scheduled", access=READ, method="GET", path="scheduled/",
    description="All recurring expense templates.",
)
def scheduled_list(ctx, args):
    qs = (
        ScheduledExpense.objects.filter(owning_feuser=ctx.feuser)
        .select_related("category").prefetch_related("tags").order_by("title")
    )
    return {"scheduled": [scheduled_json(s) for s in qs]}


@operation(
    "scheduled_get", concern="scheduled", access=READ, method="GET", path="scheduled/<int:id>/",
    description="One recurring expense template.", params={"id": ID}, required=["id"],
)
def scheduled_get(ctx, args):
    return scheduled_json(_get(ctx.feuser, args["id"]))


@operation(
    "scheduled_create", concern="scheduled", access=WRITE, method="POST", path="scheduled/",
    description="Create a recurring expense; due occurrences of the current financial year are generated at once.",
    params=SCHEDULED_FIELDS,
    required=["title", "type", "value", "repeat_every_factor", "repeat_every_unit", "repeat_base_date"],
    status=201,
)
def scheduled_create(ctx, args):
    feuser = ctx.feuser
    form = ScheduledExpenseForm(form_data(None, _FORM_FIELDS, _changes(args), _RENAMES), feuser=feuser)
    if not form.is_valid():
        raise form_errors(form, _RENAMES)
    buddy = parse_assignment_arg(feuser, args["assignment"], form.cleaned_data["type"]) if args.get("assignment") else None
    obj = scheduled_service.save_new_scheduled(feuser, form.save(commit=False), form.cleaned_data["tags"], buddy)
    return scheduled_json(_get(feuser, obj.uid))


@operation(
    "scheduled_update", concern="scheduled", access=WRITE, method="PATCH", path="scheduled/<int:id>/",
    description=(
        "Change a recurring expense; only given fields change. Repeat factor/unit change only with "
        "confirm_modify_schedule (regenerates this financial year's occurrences, settled ones too); "
        "base date/end only with confirm_modify_schedule_window. Unconfirmed changes are discarded."
    ),
    params={
        "id": ID, **SCHEDULED_FIELDS,
        "confirm_modify_schedule": {"type": "boolean"},
        "confirm_modify_schedule_window": {"type": "boolean"},
    },
    required=["id"],
)
def scheduled_update(ctx, args):
    feuser = ctx.feuser
    obj = _get(feuser, args["id"])
    confirm_schedule = bool(args.get("confirm_modify_schedule"))
    confirm_window = bool(args.get("confirm_modify_schedule_window"))
    changes = _changes(args)
    if not confirm_schedule:
        changes = {k: v for k, v in changes.items() if k not in scheduled_service.SCHEDULE_FIELDS}
    if not confirm_window:
        changes = {k: v for k, v in changes.items() if k not in scheduled_service.WINDOW_FIELDS}
    form = ScheduledExpenseForm(form_data(obj, _FORM_FIELDS, changes, _RENAMES), instance=obj, feuser=feuser)
    if not form.is_valid():
        raise form_errors(form, _RENAMES)
    keep = "assignment" not in args
    if keep and obj.assign_buddy_mode and form.cleaned_data["type"] != "expense":
        from budget.expense_service import BUDDY_TYPE_CONFLICT_MSG
        raise OpError(BUDDY_TYPE_CONFLICT_MSG)
    buddy = None if keep else parse_assignment_arg(feuser, args["assignment"], form.cleaned_data["type"])
    scheduled_service.update_scheduled(
        feuser, form.save(commit=False), form.cleaned_data["tags"], buddy,
        confirm_schedule=confirm_schedule, confirm_window=confirm_window, keep_assignment=keep,
    )
    return scheduled_json(_get(feuser, obj.uid))


@operation(
    "scheduled_delete", concern="scheduled", access=WRITE, method="DELETE", path="scheduled/<int:id>/",
    description="Delete a recurring expense template; expenses it already generated stay.",
    params={"id": ID}, required=["id"], destructive=True, status=204,
)
def scheduled_delete(ctx, args):
    _get(ctx.feuser, args["id"]).delete()
    return None


@operation(
    "scheduled_clone", concern="scheduled", access=WRITE, method="POST", path="scheduled/<int:id>/clone/",
    description="Copy a recurring expense template as \"CLONE - <title>\".",
    params={"id": ID}, required=["id"], status=201,
)
def scheduled_clone(ctx, args):
    return scheduled_json(scheduled_service.clone_scheduled(_get(ctx.feuser, args["id"])))


@operation(
    "scheduled_generated", concern="scheduled", access=READ, method="GET", path="scheduled/<int:id>/expenses/",
    description="Expenses this template generated in the current financial year.",
    params={"id": ID}, required=["id"],
)
def scheduled_generated(ctx, args):
    obj = _get(ctx.feuser, args["id"])
    return {"expenses": [
        {"id": e.uid, "date_due": e.date_due.isoformat() if e.date_due else None, "value": str(e.value), "settled": e.settled}
        for e in scheduled_service.current_year_expenses(ctx.feuser, obj).order_by("date_due")
    ]}


@operation(
    "scheduled_apply", concern="scheduled", access=WRITE, method="POST", path="scheduled/<int:id>/apply/",
    description=(
        "Copy the template's current fields and sharing onto some of its generated expenses "
        "(ids from scheduled_generated). Resets participant approvals on them."
    ),
    params={"id": ID, "expense_ids": {"type": "array", "items": {"type": "integer"}}},
    required=["id", "expense_ids"],
)
def scheduled_apply(ctx, args):
    obj = _get(ctx.feuser, args["id"])
    return {"updated": scheduled_service.apply_to_expenses(ctx.feuser, obj, args["expense_ids"])}
