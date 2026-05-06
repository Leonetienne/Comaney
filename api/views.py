from datetime import date
from decimal import Decimal

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from budget.date_utils import financial_month_range, financial_year_range
from budget.expense_factory import create_expense
from budget.models import Category, Expense, ScheduledExpense, Tag, TransactionType
from budget.query_parser import apply_query
from budget.notifications import send_settled_notification, set_initial_notification_class
from .serializers import (
    _expense_json, _scheduled_json,
    _apply_expense_fields, _apply_scheduled_fields, _set_tags,
)
from .utils import _err, _ok, _parse_body, _parse_month, _require_auth


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

@csrf_exempt
@_require_auth
def expenses(request, feuser):
    if request.method == "GET":
        year, month = _parse_month(request, feuser)
        view = request.GET.get("view")
        if view == "year":
            start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
        else:
            start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)
        qs = (
            Expense.objects
            .filter(owning_feuser=feuser, date_due__gte=start, date_due__lte=end)
            .select_related("category")
            .prefetch_related("tags")
            .order_by("date_due", "date_created")
        )
        qs = apply_query(qs, request.GET.get("q", ""))
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
        set_initial_notification_class(exp)
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
        was_settled = exp.settled
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
        if not was_settled and exp.settled:
            send_settled_notification(exp)
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
            "email_notifications":        feuser.email_notifications,
        })

    if request.method == "PATCH":
        data = _parse_body(request)
        if data is None:
            return _err("Invalid JSON body.")
        update_fields = []
        if "first_name" in data:
            v = str(data["first_name"])
            if len(v) > 128:
                return _err("'first_name' must be 128 characters or fewer.")
            feuser.first_name = v
            update_fields.append("first_name")
        if "last_name" in data:
            v = str(data["last_name"])
            if len(v) > 128:
                return _err("'last_name' must be 128 characters or fewer.")
            feuser.last_name = v
            update_fields.append("last_name")
        if "currency" in data:
            v = str(data["currency"])
            if len(v) > 10:
                return _err("'currency' must be 10 characters or fewer.")
            feuser.currency = v
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
        if "email_notifications" in data:
            feuser.email_notifications = bool(data["email_notifications"])
            update_fields.append("email_notifications")
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
            "email_notifications":        feuser.email_notifications,
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

    qs = Expense.objects.filter(owning_feuser=feuser, date_due__gte=start, date_due__lte=end, deactivated=False)

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
        title = str(data.get("title", "")).strip()
        if not title:
            return _err("'title' is required.")
        if len(title) > 128:
            return _err("'title' must be 128 characters or fewer.")
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
            title = str(data["title"]).strip()
            if not title:
                return _err("'title' must not be empty.")
            if len(title) > 128:
                return _err("'title' must be 128 characters or fewer.")
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
        title = str(data.get("title", "")).strip()
        if not title:
            return _err("'title' is required.")
        if len(title) > 128:
            return _err("'title' must be 128 characters or fewer.")
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
            title = str(data["title"]).strip()
            if not title:
                return _err("'title' must not be empty.")
            if len(title) > 128:
                return _err("'title' must be 128 characters or fewer.")
            tag.title = title
            tag.save(update_fields=["title"])
        return _ok({"id": tag.uid, "title": tag.title})

    if request.method == "DELETE":
        tag.delete()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)
