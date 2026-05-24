from datetime import date

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from budget.date_utils import financial_month_range, financial_year_range
from budget.models import Expense, TransactionType
from budget.query_parser import apply_query, has_date_filter
from budget.notifications import send_settled_notification, set_initial_notification_class
from budget.views._sharing import build_shared_qs
from ..serializers import _expense_json, _apply_expense_fields, _set_tags
from ..utils import _err, _ok, _parse_body, _parse_month, _require_auth


@csrf_exempt
@_require_auth
def expenses(request, feuser):
    if request.method == "GET":
        date_from_raw = request.GET.get("date_from")
        date_to_raw   = request.GET.get("date_to")
        q_str = request.GET.get("q", "")

        if date_from_raw and date_to_raw:
            try:
                start = date.fromisoformat(date_from_raw)
                end   = date.fromisoformat(date_to_raw)
            except ValueError:
                return _err("Invalid date_from or date_to.")
        else:
            year, month = _parse_month(request, feuser)
            view = request.GET.get("view")
            if view == "year":
                start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
            else:
                start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)

        sharing = request.GET.get("sharing", "")
        shared_mode = sharing == "shared"

        _sort_field_map = {
            "title": "title",
            "payee": "payee",
            "value": "effective_value" if shared_mode else "value",
            "date": "date_due",
        }
        sort_by = request.GET.get("sort_by", "date")
        sort_dir = request.GET.get("sort_dir", "desc")
        sort_field = _sort_field_map.get(sort_by, "date_due")
        if sort_dir == "desc":
            sort_field = "-" + sort_field

        date_filtered_by_query = has_date_filter(q_str)
        eff_start = None if date_filtered_by_query else start
        eff_end   = None if date_filtered_by_query else end

        if shared_mode:
            qs = (
                build_shared_qs(feuser, eff_start, eff_end)
                .select_related("category", "project", "owning_feuser", "upfront_payee_dummy")
                .prefetch_related(
                    "tags",
                    "buddy_spendings__participant_feuser",
                    "buddy_spendings__participant_dummy",
                )
                .order_by(sort_field, "date_created")
            )
        else:
            date_filter = {} if date_filtered_by_query else {"date_due__gte": start, "date_due__lte": end}
            qs = (
                Expense.objects
                .filter(owning_feuser=feuser, is_dummy=False, **date_filter)
                .select_related("category", "project")
                .prefetch_related(
                    "tags",
                    "buddy_spendings__participant_feuser",
                    "buddy_spendings__participant_dummy",
                )
                .order_by(sort_field, "date_created")
            )

        qs = apply_query(qs, q_str, feuser=feuser)
        expenses = list(qs)

        overlays = {}
        if shared_mode:
            foreign_ids = [e.uid for e in expenses if e.owning_feuser_id != feuser.pk]
            if foreign_ids:
                from budget.models import ExpenseDataOverlay
                overlays = {
                    ov.expense_id: ov
                    for ov in ExpenseDataOverlay.objects.filter(
                        expense_id__in=foreign_ids, feuser=feuser,
                    ).select_related("category").prefetch_related("tags")
                }

        expenses_json = [
            _expense_json(
                e,
                effective_value=getattr(e, 'effective_value', None),
                is_foreign=(e.owning_feuser_id != feuser.pk),
                overlay=overlays.get(e.uid),
            )
            for e in expenses
        ]
        return _ok({"expenses": expenses_json})

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
            .select_related("category", "project")
            .prefetch_related("tags")
            .get(uid=uid, owning_feuser=feuser)
        )
    except Expense.DoesNotExist:
        return _err("Expense not found.", 404)

    if request.method == "GET":
        return _ok(_expense_json(exp))

    if exp.type == "carry_over":
        return _err("Carry-over entries cannot be modified or deleted.", 403)

    if exp.is_buddies_settlement:
        if request.method == "PATCH":
            return _err("Settlement expenses cannot be edited.", 403)
        if request.method == "DELETE":
            has_dummy_creditor = exp.buddy_spendings.filter(
                participant_dummy__isnull=False
            ).exists()
            if not has_dummy_creditor:
                if exp.buddy_approved:
                    return _err("Approved settlement expenses cannot be deleted.", 403)
                from buddies.services import BuddyEmailService
                bs = exp.buddy_spendings.select_related("participant_feuser").filter(
                    participant_feuser__isnull=False
                ).first()
                if bs:
                    BuddyEmailService.send_settlement_cancelled_notification(
                        exp, bs.participant_feuser
                    )
            _proj = exp.project
            exp.delete()
            if _proj:
                _proj.update_lastmod()
            return JsonResponse({}, status=204)

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
        if exp.project:
            exp.project.update_lastmod()
        exp.refresh_from_db()
        return _ok(_expense_json(exp))

    if request.method == "DELETE":
        _proj = exp.project
        exp.delete()
        if _proj:
            _proj.update_lastmod()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)
