import json
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from budget.date_utils import current_financial_month, financial_month_range
from budget.expense_factory import create_expense
from budget.models import Category, Expense, ScheduledExpense, Tag, TransactionType
from .auth import get_api_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg, status=400):
    return JsonResponse({"error": msg}, status=status)


def _ok(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def _require_auth(fn):
    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        user = get_api_user(request)
        if not user:
            return _err("Unauthorized — provide a valid Bearer token.", 401)
        return fn(request, user, *args, **kwargs)
    return wrapper


def _parse_body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None


def _parse_month(request, feuser):
    """Return (year, month) from query params.

    Either param may be omitted independently; missing values fall back to the
    corresponding component of the user's current financial month rather than
    requiring both or neither.
    """
    cur_year, cur_month = current_financial_month(feuser.month_start_day, feuser.month_start_prev)
    try:
        year = int(request.GET["year"])
    except (KeyError, ValueError):
        year = cur_year
    try:
        month = int(request.GET["month"])
    except (KeyError, ValueError):
        month = cur_month
    return year, month


def _expense_json(exp):
    return {
        "id":                      exp.uid,
        "title":                   exp.title,
        "payee":                   exp.payee,
        "type":                    exp.type,
        "value":                   str(exp.value),
        "category":                {"id": exp.category.uid, "title": exp.category.title} if exp.category else None,
        "tags":                    [{"id": t.uid, "title": t.title} for t in exp.tags.all()],
        "note":                    exp.note,
        "date_due":                exp.date_due.isoformat() if exp.date_due else None,
        "settled":                 exp.settled,
        "auto_settle_on_due_date": exp.auto_settle_on_due_date,
        "date_created":            exp.date_created.isoformat(),
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
    }


def _apply_expense_fields(obj, data, feuser, creating=False):
    """Apply fields from request data onto an Expense or dict. Returns error string or None."""
    if "title" in data:
        obj.title = str(data["title"])[:255]
    elif creating and not getattr(obj, "title", None):
        return "'title' is required."

    if "payee" in data:
        obj.payee = str(data["payee"] or "")[:255]
    if "note" in data:
        obj.note = str(data["note"] or "")
    if "settled" in data:
        obj.settled = bool(data["settled"])
    if "auto_settle_on_due_date" in data:
        obj.auto_settle_on_due_date = bool(data["auto_settle_on_due_date"])

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

    return None


def _apply_scheduled_fields(obj, data, feuser, creating=False):
    if "title" in data:
        obj.title = str(data["title"])[:255]
    elif creating and not getattr(obj, "title", None):
        return "'title' is required."

    if "payee" in data:
        obj.payee = str(data["payee"] or "")[:255]
    if "note" in data:
        obj.note = str(data["note"] or "")
    if "default_auto_settle_on_due_date" in data:
        obj.default_auto_settle_on_due_date = bool(data["default_auto_settle_on_due_date"])

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

    if "category_id" in data:
        if data["category_id"]:
            try:
                obj.category = Category.objects.get(uid=data["category_id"], owning_feuser=feuser)
            except Category.DoesNotExist:
                return f"Category {data['category_id']} not found."
        else:
            obj.category = None

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


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

@csrf_exempt
@_require_auth
def expenses(request, feuser):
    if request.method == "GET":
        year, month = _parse_month(request, feuser)
        start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)
        qs = (
            Expense.objects
            .filter(owning_feuser=feuser, date_due__gte=start, date_due__lte=end)
            .select_related("category")
            .prefetch_related("tags")
            .order_by("date_due", "date_created")
        )
        return _ok({"year": year, "month": month, "expenses": [_expense_json(e) for e in qs]})

    if request.method == "POST":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        exp = Expense(owning_feuser=feuser, settled=True, auto_settle_on_due_date=False, date_due=date.today())
        err = _apply_expense_fields(exp, data, feuser, creating=True)
        if err:
            return _err(err)
        exp.save()
        tag_err = _set_tags(exp, data, feuser)
        if tag_err:
            return _err(tag_err)
        return _ok(_expense_json(exp), 201)

    return _err("Method not allowed.", 405)


@csrf_exempt
@_require_auth
def expense_detail(request, feuser, uid):
    try:
        exp = (
            Expense.objects
            .select_related("category")
            .prefetch_related("tags")
            .get(uid=uid, owning_feuser=feuser)
        )
    except Expense.DoesNotExist:
        return _err("Expense not found.", 404)

    if request.method == "GET":
        return _ok(_expense_json(exp))

    if exp.type == "carry_over":
        return _err("Carry-over entries cannot be modified or deleted.", 403)

    if request.method == "PATCH":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        err = _apply_expense_fields(exp, data, feuser)
        if err:
            return _err(err)
        exp.save()
        tag_err = _set_tags(exp, data, feuser)
        if tag_err:
            return _err(tag_err)
        exp.refresh_from_db()
        return _ok(_expense_json(exp))

    if request.method == "DELETE":
        exp.delete()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)


# ---------------------------------------------------------------------------
# Scheduled expenses
# ---------------------------------------------------------------------------

@csrf_exempt
@_require_auth
def scheduled(request, feuser):
    if request.method == "GET":
        qs = (
            ScheduledExpense.objects
            .filter(owning_feuser=feuser)
            .select_related("category")
            .prefetch_related("tags")
            .order_by("title")
        )
        return _ok({"scheduled": [_scheduled_json(s) for s in qs]})

    if request.method == "POST":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        s = ScheduledExpense(owning_feuser=feuser, default_auto_settle_on_due_date=False)
        err = _apply_scheduled_fields(s, data, feuser, creating=True)
        if err:
            return _err(err)
        s.save()
        tag_err = _set_tags(s, data, feuser)
        if tag_err:
            return _err(tag_err)
        return _ok(_scheduled_json(s), 201)

    return _err("Method not allowed.", 405)


@csrf_exempt
@_require_auth
def scheduled_detail(request, feuser, uid):
    try:
        s = (
            ScheduledExpense.objects
            .select_related("category")
            .prefetch_related("tags")
            .get(uid=uid, owning_feuser=feuser)
        )
    except ScheduledExpense.DoesNotExist:
        return _err("Scheduled expense not found.", 404)

    if request.method == "GET":
        return _ok(_scheduled_json(s))

    if request.method == "PATCH":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        err = _apply_scheduled_fields(s, data, feuser)
        if err:
            return _err(err)
        s.save()
        tag_err = _set_tags(s, data, feuser)
        if tag_err:
            return _err(tag_err)
        s.refresh_from_db()
        return _ok(_scheduled_json(s))

    if request.method == "DELETE":
        s.delete()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

@csrf_exempt
@_require_auth
def account(request, feuser):
    if request.method == "GET":
        return _ok({
            "email":                      feuser.email,
            "first_name":                 feuser.first_name,
            "last_name":                  feuser.last_name,
            "currency":                   feuser.currency,
            "month_start_day":            feuser.month_start_day,
            "month_start_prev":           feuser.month_start_prev,
            "unspent_allowance_action":   feuser.unspent_allowance_action,
            "allowance_transition_month": feuser.allowance_transition_month,
        })

    if request.method == "PATCH":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        update_fields = []
        if "first_name" in data:
            feuser.first_name = str(data["first_name"])[:150]
            update_fields.append("first_name")
        if "last_name" in data:
            feuser.last_name = str(data["last_name"])[:150]
            update_fields.append("last_name")
        if "currency" in data:
            feuser.currency = str(data["currency"])[:10]
            update_fields.append("currency")
        if "month_start_day" in data:
            try:
                day = int(data["month_start_day"])
                if not 1 <= day <= 31:
                    return _err("'month_start_day' must be 1–31.")
                feuser.month_start_day = day
                update_fields.append("month_start_day")
            except (ValueError, TypeError):
                return _err("'month_start_day' must be an integer.")
        if "month_start_prev" in data:
            feuser.month_start_prev = bool(data["month_start_prev"])
            update_fields.append("month_start_prev")
        if "unspent_allowance_action" in data:
            valid = {"do_nothing", "deposit_savings", "carry_over"}
            val = str(data["unspent_allowance_action"])
            if val not in valid:
                return _err(f"'unspent_allowance_action' must be one of: {', '.join(sorted(valid))}.")
            feuser.unspent_allowance_action = val
            update_fields.append("unspent_allowance_action")
        if "allowance_transition_month" in data:
            feuser.allowance_transition_month = str(data["allowance_transition_month"])[:10]
            update_fields.append("allowance_transition_month")
        if update_fields:
            feuser.save(update_fields=update_fields)
        return _ok({
            "email":                      feuser.email,
            "first_name":                 feuser.first_name,
            "last_name":                  feuser.last_name,
            "currency":                   feuser.currency,
            "month_start_day":            feuser.month_start_day,
            "month_start_prev":           feuser.month_start_prev,
            "unspent_allowance_action":   feuser.unspent_allowance_action,
            "allowance_transition_month": feuser.allowance_transition_month,
        })

    return _err("Method not allowed.", 405)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@csrf_exempt
@_require_auth
def dashboard(request, feuser):
    if request.method != "GET":
        return _err("Method not allowed.", 405)

    year, month = _parse_month(request, feuser)
    start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)

    qs = Expense.objects.filter(owning_feuser=feuser, date_due__gte=start, date_due__lte=end)

    def _sum(fqs):
        return sum(e.value for e in fqs) or Decimal("0.00")

    income      = _sum(qs.filter(type="income"))
    paid        = _sum(qs.filter(type="expense", settled=True))
    outstanding = _sum(qs.filter(type="expense", settled=False))
    sav_dep     = _sum(qs.filter(type="savings_dep"))
    sav_wit     = _sum(qs.filter(type="savings_wit"))

    return _ok({
        "year":                 year,
        "month":                month,
        "month_range":          {"start": start.isoformat(), "end": end.isoformat()},
        "currency":             feuser.currency,
        "income":               str(income),
        "expenses_paid":        str(paid),
        "expenses_outstanding": str(outstanding),
        "savings_deposited":    str(sav_dep),
        "savings_withdrawn":    str(sav_wit),
        "balance":              str(income - paid - outstanding - (sav_dep - sav_wit)),
    })


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@csrf_exempt
@_require_auth
def categories(request, feuser):
    if request.method == "GET":
        qs = Category.objects.filter(owning_feuser=feuser)
        return _ok({"categories": [{"id": c.uid, "title": c.title} for c in qs]})

    if request.method == "POST":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        title = str(data.get("title", "")).strip()[:255]
        if not title:
            return _err("'title' is required.")
        cat = Category.objects.create(owning_feuser=feuser, title=title)
        return _ok({"id": cat.uid, "title": cat.title}, 201)

    return _err("Method not allowed.", 405)


@csrf_exempt
@_require_auth
def category_detail(request, feuser, uid):
    try:
        cat = Category.objects.get(uid=uid, owning_feuser=feuser)
    except Category.DoesNotExist:
        return _err("Category not found.", 404)

    if request.method == "GET":
        return _ok({"id": cat.uid, "title": cat.title})

    if request.method == "PATCH":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        if "title" in data:
            title = str(data["title"]).strip()[:255]
            if not title:
                return _err("'title' must not be empty.")
            cat.title = title
            cat.save(update_fields=["title"])
        return _ok({"id": cat.uid, "title": cat.title})

    if request.method == "DELETE":
        cat.delete()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@csrf_exempt
@_require_auth
def tags(request, feuser):
    if request.method == "GET":
        qs = Tag.objects.filter(owning_feuser=feuser)
        return _ok({"tags": [{"id": t.uid, "title": t.title} for t in qs]})

    if request.method == "POST":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        title = str(data.get("title", "")).strip()[:255]
        if not title:
            return _err("'title' is required.")
        tag = Tag.objects.create(owning_feuser=feuser, title=title)
        return _ok({"id": tag.uid, "title": tag.title}, 201)

    return _err("Method not allowed.", 405)


@csrf_exempt
@_require_auth
def tag_detail(request, feuser, uid):
    try:
        tag = Tag.objects.get(uid=uid, owning_feuser=feuser)
    except Tag.DoesNotExist:
        return _err("Tag not found.", 404)

    if request.method == "GET":
        return _ok({"id": tag.uid, "title": tag.title})

    if request.method == "PATCH":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        if "title" in data:
            title = str(data["title"]).strip()[:255]
            if not title:
                return _err("'title' must not be empty.")
            tag.title = title
            tag.save(update_fields=["title"])
        return _ok({"id": tag.uid, "title": tag.title})

    if request.method == "DELETE":
        tag.delete()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)
