"""Argument schemas, period resolution, form bridging and JSON shapes shared by the operations."""
from datetime import date
from decimal import Decimal

from django.forms.models import model_to_dict

from budget.date_utils import current_financial_month, financial_month_range, financial_year_range, year_in_range
from budget.expense_service import parse_assignment
from feusers.templatetags.feuser_tags import avatar_color

from ..registry import OpError

# ---------------------------------------------------------------------------
# Reusable schema fragments
# ---------------------------------------------------------------------------

ID = {"type": "integer", "description": "Record id."}
DATE = {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD."}
MONEY = {"type": ["string", "number"], "description": "Positive amount, two decimals."}
TYPE = {"type": "string", "enum": ["expense", "income", "savings_dep", "savings_wit"]}

PERIOD_PARAMS = {
    "date_from": {"type": "string", "description": "ISO start date; needs date_to."},
    "date_to":   {"type": "string", "description": "ISO end date; needs date_from."},
    "year":      {"type": "integer", "description": "Financial year (default current)."},
    "month":     {"type": "integer", "description": "Financial month 1-12 (default current)."},
    "view":      {"type": "string", "enum": ["month", "year"], "description": "Whole financial year or month."},
}

SHARING = {
    "type": "string", "enum": ["", "personal", "shared"],
    "description": "personal: own expenses at full value. shared: own and foreign expenses at the feuser's share.",
}

ASSIGNMENT = {
    "type": ["object", "null"],
    "description": (
        "Share the expense with a contact or project; null makes it personal. "
        "mode contact: at most one participant. payer: who paid upfront (default me). "
        "participants: shares in percent; the payer keeps the remainder."
    ),
    "properties": {
        "mode": {"type": "string", "enum": ["contact", "project"]},
        "project_id": {"type": "integer"},
        "payer": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["me", "feuser", "offline"]},
                "id": {"type": "integer"},
            },
        },
        "participants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["feuser", "offline"]},
                    "id": {"type": "integer"},
                    "share_percent": {"type": "number"},
                },
                "required": ["type", "id", "share_percent"],
            },
        },
    },
    "required": ["mode"],
}

_ID_TYPES = {"feuser": "feuser", "offline": "dummy"}


def parse_assignment_arg(feuser, value, expense_type):
    """ASSIGNMENT argument -> parse_assignment() result, None for null. Raises OpError when invalid."""
    from budget.expense_service import BUDDY_TYPE_CONFLICT_MSG

    if value is None:
        return None
    mode = {"contact": "single", "project": "group"}.get(value.get("mode"))
    if not mode:
        raise OpError("'assignment.mode' must be contact or project.")
    payer = value.get("payer") or {"type": "me"}
    payer_type = {"me": "me", "feuser": "feuser", "offline": "dummy"}.get(payer.get("type"))
    if not payer_type:
        raise OpError("'assignment.payer.type' must be me, feuser or offline.")
    spendings = []
    for p in value.get("participants") or []:
        if not isinstance(p, dict) or p.get("type") not in _ID_TYPES:
            raise OpError("Each participant needs type feuser or offline, id and share_percent.")
        try:
            spendings.append({"type": _ID_TYPES[p["type"]], "id": int(p["id"]), "share_percent": float(p["share_percent"])})
        except (KeyError, TypeError, ValueError):
            raise OpError("Each participant needs type feuser or offline, id and share_percent.")
    buddy = parse_assignment(
        feuser, mode=mode, upfront_type=payer_type, upfront_id=payer.get("id"),
        project_id=value.get("project_id"), spendings=spendings, expense_type=expense_type,
    )
    if buddy["type_conflict"]:
        raise OpError(BUDDY_TYPE_CONFLICT_MSG)
    if not buddy["valid"]:
        raise OpError(
            "Invalid assignment: unknown or unconnected project, payer or participant, "
            "a contact expense without exactly one participant, or shares out of range."
        )
    return buddy


def assignment_json(expense, feuser):
    from budget.expense_service import current_assignment
    buddy = current_assignment(expense, feuser)
    if buddy is None:
        return None
    payer = {"type": "me"}
    if buddy["upfront_type"] == "dummy" and buddy["upfront_dummy"]:
        payer = {"type": "offline", "id": buddy["upfront_dummy"].pk}
    return {
        "mode": "project" if buddy["mode"] == "group" else "contact",
        "project_id": expense.project_id,
        "payer": payer,
        "participants": [
            {"type": "offline" if s["type"] == "dummy" else "feuser", "id": s["id"], "share_percent": s["share_percent"]}
            for s in buddy["spendings"]
        ],
    }


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

def _parse_date(name, value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise OpError(f"'{name}' must be an ISO date (YYYY-MM-DD).")


def resolve_period(feuser, args) -> tuple[date, date]:
    """date_from/date_to when both are given, else the financial month or year (default current)."""
    if args.get("date_from") and args.get("date_to"):
        return _parse_date("date_from", args["date_from"]), _parse_date("date_to", args["date_to"])
    cur_year, cur_month = current_financial_month(feuser.month_start_day, feuser.month_start_prev)
    year = args.get("year", cur_year)
    if not year_in_range(year):
        year = cur_year
    month = args.get("month", cur_month)
    if not 1 <= month <= 12:
        month = cur_month
    if args.get("view") == "year":
        return financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
    return financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

def form_data(instance, fields, changes, renames):
    """
    Build a Django form data dict: the instance's stored values overlaid with
    `changes` (API names, mapped through `renames`). Booleans follow checkbox
    semantics, so False is left out.
    """
    data = model_to_dict(instance, fields=fields) if instance is not None and instance.pk else {}
    if "tags" in data:
        data["tags"] = [t.pk for t in data["tags"]]
    for api_name, value in changes.items():
        data[renames.get(api_name, api_name)] = value
    out = {}
    for key, value in data.items():
        if value is None or value is False:
            continue
        out[key] = str(value) if hasattr(value, "quantize") or isinstance(value, float) else value
    return out


def form_errors(form, renames):
    """First form error as an OpError, named by its API field."""
    reverse = {v: k for k, v in renames.items()}
    for field, messages in form.errors.items():
        name = reverse.get(field, field)
        prefix = "" if field == "__all__" else f"'{name}': "
        return OpError(prefix + " ".join(messages))
    return OpError("Invalid input.")


# ---------------------------------------------------------------------------
# JSON shapes
# ---------------------------------------------------------------------------

def person_name(feuser) -> str:
    return f"{feuser.first_name} {feuser.last_name}".strip() or feuser.email


def feuser_json(fu) -> dict:
    return {"type": "feuser", "id": fu.pk, "name": person_name(fu), "email": fu.email}


def dummy_json(du) -> dict:
    return {"type": "offline", "id": du.pk, "name": du.display_name}


def ref_json(obj):
    return {"id": obj.uid, "title": obj.title} if obj else None


def _avatar(name, initials, picture_url):
    return {"name": name, "initials": initials, "ppic_url": picture_url, "color": avatar_color(initials)}


def buddy_participants(exp) -> list:
    """Payer first, then participants; the avatar list the expense list page renders."""
    participants = []
    for bs in exp.buddy_spendings.all():
        if bs.participant_feuser_id:
            fu = bs.participant_feuser
            row = _avatar(person_name(fu), fu.initials, fu.ppic_url if fu.profile_picture else None)
            row.update(approval_state=bs.approval_state, is_payer=False)
        else:
            du = bs.participant_dummy
            row = _avatar(du.display_name, du.initials, du.ppic_url if du.profile_picture else None)
            row.update(approval_state=None, is_payer=False)
        participants.append(row)
    if exp.is_dummy and exp.upfront_payee_dummy_id:
        du = exp.upfront_payee_dummy
        payer = _avatar(du.display_name, du.initials, du.ppic_url if du.profile_picture else None)
        payer.update(approval_state=None, is_payer=True)
    else:
        fu = exp.owning_feuser
        payer = _avatar(person_name(fu), fu.initials, fu.ppic_url if fu.profile_picture else None)
        payer.update(approval_state=1 if exp.buddy_approved else 0, is_payer=True)
    return [payer] + participants


def expense_json(exp, effective_value=None, is_foreign=False, overlay=None) -> dict:
    """An expense as feuser sees it: a foreign expense shows feuser's own overlay classification."""
    if is_foreign:
        cat = overlay.category if overlay else None
        tags = list(overlay.tags.all()) if overlay else []
    else:
        cat = exp.category
        tags = list(exp.tags.all())
    return {
        "id":                           exp.uid,
        "title":                        exp.title,
        "payee":                        exp.payee,
        "type":                         exp.type,
        "value":                        str(exp.value),
        "effective_value":              str(Decimal(effective_value).quantize(Decimal("0.01"))) if effective_value is not None else None,
        "is_foreign":                   is_foreign,
        "category":                     ref_json(cat),
        "tags":                         [ref_json(t) for t in tags],
        "note":                         exp.note,
        "date_due":                     exp.date_due.isoformat() if exp.date_due else None,
        "settled":                      exp.settled,
        "auto_settle_on_due_date":      exp.auto_settle_on_due_date,
        "deactivated":                  exp.deactivated,
        "notify":                       exp.notify,
        "last_notification_class_sent": exp.last_notification_class_sent,
        "date_created":                 exp.date_created.isoformat(),
        "buddy_participants":           buddy_participants(exp),
        "is_buddies_settlement":        exp.is_buddies_settlement,
        "can_delete":                   exp.settlement_can_delete and not is_foreign,
        "can_edit":                     exp.settlement_can_edit and not is_foreign,
        "project":                      {"id": exp.project_id, "name": exp.project.name} if exp.project_id else None,
    }


def scheduled_json(s) -> dict:
    return {
        "id":                              s.uid,
        "title":                           s.title,
        "payee":                           s.payee,
        "type":                            s.type,
        "value":                           str(s.value),
        "category":                        ref_json(s.category),
        "tags":                            [ref_json(t) for t in s.tags.all()],
        "note":                            s.note,
        "default_auto_settle_on_due_date": s.default_auto_settle_on_due_date,
        "notify":                          s.notify,
        "repeat_every_factor":             s.repeat_every_factor,
        "repeat_every_unit":               s.repeat_every_unit,
        "repeat_base_date":                s.repeat_base_date.isoformat() if s.repeat_base_date else None,
        "end_on":                          s.end_on.isoformat() if s.end_on else None,
        "deactivated":                     s.deactivated,
    }
