from django.core.management import call_command
from django.http import JsonResponse

from budget.date_utils import current_financial_month, financial_year_range
from budget.models import Expense, ScheduledExpense
from ..serializers import _scheduled_json, _apply_scheduled_fields, _set_tags
from ..utils import _err, _ok, _parse_body, _require_auth


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
        call_command("generate_scheduled_expenses", user=feuser.email)
        return _ok(_scheduled_json(s), 201)

    return _err("Method not allowed.", 405)


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

        # Gate A/B: same protection as the web form (see scheduled_form.html /
        # views.scheduled.scheduled_edit). The checkbox is a UI affordance for
        # consent; the actual safety mechanism is server-side and client-agnostic,
        # so the API PATCH body requires the same explicit confirmation flags.
        old_factor, old_unit = s.repeat_every_factor, s.repeat_every_unit
        old_base, old_end = s.repeat_base_date, s.end_on
        confirm_a = bool(data.get("confirm_modify_schedule"))
        confirm_b = bool(data.get("confirm_modify_schedule_window"))
        if not confirm_a:
            data.pop("repeat_every_factor", None)
            data.pop("repeat_every_unit", None)
        if not confirm_b:
            data.pop("repeat_base_date", None)
            data.pop("end_on", None)

        err = _apply_scheduled_fields(s, data, feuser)
        if err:
            return _err(err)
        s.save()
        tag_err = _set_tags(s, data, feuser)
        if tag_err:
            return _err(tag_err)

        factor_unit_changed = (old_factor, old_unit) != (s.repeat_every_factor, s.repeat_every_unit)
        window_changed = (old_base, old_end) != (s.repeat_base_date, s.end_on)

        if confirm_a and factor_unit_changed:
            year = current_financial_month(feuser.month_start_day, feuser.month_start_prev)[0]
            start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
            Expense.objects.filter(
                source_scheduled=s,
                scheduled_occurrence_date__gte=start,
                scheduled_occurrence_date__lte=end,
            ).delete()
            s.last_run = None
            s.save(update_fields=["last_run"])
        elif confirm_b and window_changed:
            s.last_run = None
            s.save(update_fields=["last_run"])

        call_command("generate_scheduled_expenses", user=feuser.email)
        s.refresh_from_db()
        return _ok(_scheduled_json(s))

    if request.method == "DELETE":
        s.delete()
        return JsonResponse({}, status=204)

    return _err("Method not allowed.", 405)
