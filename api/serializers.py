from datetime import date
from decimal import Decimal, InvalidOperation

from budget.models import Category, Tag, TransactionType
from .utils import _err


_AVATAR_COLORS = [
    "#c2478a", "#5b6af0", "#2ea8a8", "#e05c2a", "#6a9e2e", "#a855b5",
    "#d4902a", "#3a8ed4", "#e05878", "#2e8a5f", "#7c6af0", "#c47a2a",
]


def _avatar_color(initials: str) -> str:
    if not initials:
        return _AVATAR_COLORS[0]
    return _AVATAR_COLORS[hash(initials) % len(_AVATAR_COLORS)]


def _buddy_participants(exp) -> list:
    participants = []
    for bs in exp.buddy_spendings.all():
        if bs.participant_feuser_id:
            fu = bs.participant_feuser
            name = f"{fu.first_name} {fu.last_name}".strip() or fu.email
            initials = fu.initials
            participants.append({
                "name": name,
                "initials": initials,
                "ppic_url": fu.ppic_url if fu.profile_picture else None,
                "color": _avatar_color(initials),
                "approval_state": bs.approval_state,
                "is_payer": False,
            })
        elif bs.participant_dummy_id:
            du = bs.participant_dummy
            initials = du.initials
            participants.append({
                "name": du.display_name,
                "initials": initials,
                "ppic_url": du.ppic_url if du.profile_picture else None,
                "color": _avatar_color(initials),
                "approval_state": None,
                "is_payer": False,
            })
    if exp.is_dummy and exp.upfront_payee_dummy_id:
        du = exp.upfront_payee_dummy
        initials = du.initials
        payer = {
            "name": du.display_name,
            "initials": initials,
            "ppic_url": du.ppic_url if du.profile_picture else None,
            "color": _avatar_color(initials),
            "approval_state": None,
            "is_payer": True,
        }
    else:
        fu = exp.owning_feuser
        name = f"{fu.first_name} {fu.last_name}".strip() or fu.email
        initials = fu.initials
        payer = {
            "name": name,
            "initials": initials,
            "ppic_url": fu.ppic_url if fu.profile_picture else None,
            "color": _avatar_color(initials),
            "approval_state": 1 if exp.buddy_approved else 0,
            "is_payer": True,
        }
    return [payer] + participants


def _settlement_can_delete(exp) -> bool:
    return exp.settlement_can_delete


def _expense_json(exp, effective_value=None, is_foreign=False, overlay=None):
    if is_foreign:
        _cat  = overlay.category if overlay else None
        _tags = list(overlay.tags.all()) if overlay else []
    else:
        _cat  = exp.category
        _tags = list(exp.tags.all())

    return {
        "id":                           exp.uid,
        "title":                        exp.title,
        "payee":                        exp.payee,
        "type":                         exp.type,
        "value":                        str(exp.value),
        "effective_value":              str(effective_value) if effective_value is not None else None,
        "is_foreign":                   is_foreign,
        "category":                     {"id": _cat.uid, "title": _cat.title} if _cat else None,
        "tags":                         [{"id": t.uid, "title": t.title} for t in _tags],
        "note":                         exp.note,
        "date_due":                     exp.date_due.isoformat() if exp.date_due else None,
        "settled":                      exp.settled,
        "auto_settle_on_due_date":      exp.auto_settle_on_due_date,
        "deactivated":                  exp.deactivated,
        "notify":                       exp.notify,
        "last_notification_class_sent": exp.last_notification_class_sent,
        "date_created":                 exp.date_created.isoformat(),
        "buddy_participants":           _buddy_participants(exp),
        "is_buddies_settlement":        exp.is_buddies_settlement,
        "can_delete":                   _settlement_can_delete(exp) and not is_foreign,
        "can_edit":                     exp.settlement_can_edit and not is_foreign,
        "project":                      {"id": exp.project_id, "name": exp.project.name} if exp.project_id else None,
    }


def _scheduled_json(s):
    return {
        "id":                              s.uid,
        "title":                           s.title,
        "payee":                           s.payee,
        "type":                            s.type,
        "value":                           str(s.value),
        "category":                        {"id": s.category.uid, "title": s.category.title} if s.category else None,
        "tags":                            [{"id": t.uid, "title": t.title} for t in s.tags.all()],
        "note":                            s.note,
        "default_auto_settle_on_due_date": s.default_auto_settle_on_due_date,
        "repeat_every_factor":             s.repeat_every_factor,
        "repeat_every_unit":               s.repeat_every_unit,
        "repeat_base_date":                s.repeat_base_date.isoformat() if s.repeat_base_date else None,
        "end_on":                          s.end_on.isoformat() if s.end_on else None,
        "deactivated":                     s.deactivated,
    }


def _apply_expense_fields(obj, data, feuser, creating=False):
    """Apply fields from request data onto an Expense. Returns error string or None."""
    if "title" in data:
        title = str(data["title"])
        if len(title) > 128:
            return "'title' must be 128 characters or fewer."
        obj.title = title
    elif creating and not getattr(obj, "title", None):
        return "'title' is required."

    if "payee" in data:
        payee = str(data["payee"] or "")
        if len(payee) > 128:
            return "'payee' must be 128 characters or fewer."
        obj.payee = payee
    if "note" in data:
        note = str(data["note"] or "")
        if len(note) > 1024:
            return "'note' must be 1024 characters or fewer."
        obj.note = note
    if "settled" in data:
        obj.settled = bool(data["settled"])
    if "auto_settle_on_due_date" in data:
        obj.auto_settle_on_due_date = bool(data["auto_settle_on_due_date"])
    if "deactivated" in data:
        obj.deactivated = bool(data["deactivated"])
    if "notify" in data:
        obj.notify = bool(data["notify"])

    if "type" in data:
        if data["type"] not in ("expense", "income", "savings_dep", "savings_wit"):
            return f"Invalid type '{data['type']}'."
        obj.type = data["type"]
    elif creating and not getattr(obj, "type", None):
        return "'type' is required."

    if "value" in data:
        try:
            obj.value = Decimal(str(data["value"])).quantize(Decimal("0.01"))
            if obj.value <= 0:
                return "'value' must be positive."
        except InvalidOperation:
            return "'value' must be a valid decimal number."
    elif creating and not getattr(obj, "value", None):
        return "'value' is required."

    if "date_due" in data:
        if data["date_due"]:
            try:
                obj.date_due = date.fromisoformat(str(data["date_due"]))
            except ValueError:
                return "'date_due' must be ISO date (YYYY-MM-DD) or null."
        else:
            obj.date_due = None

    if "category_id" in data:
        if data["category_id"]:
            try:
                obj.category = Category.objects.get(uid=data["category_id"], owning_feuser=feuser)
            except Category.DoesNotExist:
                return f"Category {data['category_id']} not found."
        else:
            obj.category = None

    if obj.pk and obj.type != TransactionType.EXPENSE and (
        obj.project_id or obj.is_dummy or obj.buddy_spendings.exists()
    ):
        return 'Buddy and project expenses must be type "expense".'

    return None


def _apply_scheduled_fields(obj, data, feuser, creating=False):
    if "title" in data:
        title = str(data["title"])
        if len(title) > 128:
            return "'title' must be 128 characters or fewer."
        obj.title = title
    elif creating and not getattr(obj, "title", None):
        return "'title' is required."

    if "payee" in data:
        payee = str(data["payee"] or "")
        if len(payee) > 128:
            return "'payee' must be 128 characters or fewer."
        obj.payee = payee
    if "note" in data:
        note = str(data["note"] or "")
        if len(note) > 1024:
            return "'note' must be 1024 characters or fewer."
        obj.note = note
    if "default_auto_settle_on_due_date" in data:
        obj.default_auto_settle_on_due_date = bool(data["default_auto_settle_on_due_date"])
    if "deactivated" in data:
        obj.deactivated = bool(data["deactivated"])

    if "type" in data:
        if data["type"] not in ("expense", "income", "savings_dep", "savings_wit"):
            return f"Invalid type '{data['type']}'."
        obj.type = data["type"]
    elif creating and not getattr(obj, "type", None):
        return "'type' is required."

    if "value" in data:
        try:
            obj.value = Decimal(str(data["value"])).quantize(Decimal("0.01"))
            if obj.value <= 0:
                return "'value' must be positive."
        except InvalidOperation:
            return "'value' must be a valid decimal number."
    elif creating and not getattr(obj, "value", None):
        return "'value' is required."

    if "repeat_every_factor" in data:
        try:
            obj.repeat_every_factor = int(data["repeat_every_factor"])
        except (ValueError, TypeError):
            return "'repeat_every_factor' must be an integer."
    if "repeat_every_unit" in data:
        if data["repeat_every_unit"] not in ("days", "weeks", "months", "years"):
            return "'repeat_every_unit' must be days, weeks, months, or years."
        obj.repeat_every_unit = data["repeat_every_unit"]
    if "repeat_base_date" in data:
        if data["repeat_base_date"]:
            try:
                obj.repeat_base_date = date.fromisoformat(str(data["repeat_base_date"]))
            except ValueError:
                return "'repeat_base_date' must be ISO date (YYYY-MM-DD) or null."
        else:
            obj.repeat_base_date = None
    if "end_on" in data:
        if data["end_on"]:
            try:
                obj.end_on = date.fromisoformat(str(data["end_on"]))
            except ValueError:
                return "'end_on' must be ISO date (YYYY-MM-DD) or null."
        else:
            obj.end_on = None

    if "category_id" in data:
        if data["category_id"]:
            try:
                obj.category = Category.objects.get(uid=data["category_id"], owning_feuser=feuser)
            except Category.DoesNotExist:
                return f"Category {data['category_id']} not found."
        else:
            obj.category = None

    if obj.pk and obj.type != TransactionType.EXPENSE and obj.assign_buddy_mode:
        return 'Buddy and project scheduled expenses must be type "expense".'

    return None


def _set_tags(obj, data, feuser):
    if "tag_ids" not in data:
        return None
    tag_ids = data["tag_ids"] or []
    tags = []
    for tid in tag_ids:
        try:
            tags.append(Tag.objects.get(uid=tid, owning_feuser=feuser))
        except Tag.DoesNotExist:
            return f"Tag {tid} not found."
    obj.tags.set(tags)
    return None
