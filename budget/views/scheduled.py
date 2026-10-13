import json
import secrets
from datetime import date

from django.contrib import messages
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..date_utils import current_financial_month
from .. import scheduled_service
from ..decorators import feuser_required
from ..forms import ScheduledExpenseForm
from ..models import ScheduledExpense
from ..expense_service import BUDDY_TYPE_CONFLICT_MSG, parse_assignment_post as _parse_buddy_post
from .expenses import _buddy_context, _buddy_render_context_from_post


def _existing_assignment_ctx(obj: ScheduledExpense) -> dict:
    """Build template context for restoring existing assignment in the form."""
    if not obj.assign_buddy_mode:
        return {
            'is_buddy_expense': False,
            'existing_mode': 'single',
            'existing_upfront_type': 'me',
            'existing_upfront_id': obj.owning_feuser_id,
            'existing_spendings_json': '[]',
            'existing_group_id': None,
        }
    if obj.assign_upfront_type == 'feuser':
        upfront_id = obj.assign_upfront_feuser_id
    elif obj.assign_upfront_type == 'dummy':
        upfront_id = obj.assign_upfront_dummy_id
    else:
        upfront_id = obj.owning_feuser_id
    return {
        'is_buddy_expense': True,
        'existing_mode': obj.assign_buddy_mode,
        'existing_upfront_type': obj.assign_upfront_type,
        'existing_upfront_id': upfront_id,
        'existing_spendings_json': obj.assign_spendings_json or '[]',
        'existing_group_id': obj.assign_project_id if obj.assign_buddy_mode == 'group' else None,
        # Editing a saved schedule: respect its stored participant selection
        # (including an empty one) instead of pre-checking every member.
        'respect_existing_participants': True,
    }


@feuser_required
def scheduled_list(request):
    scheduled = (
        ScheduledExpense.objects.filter(owning_feuser=request.feuser)
        .select_related("category")
        .prefetch_related("tags")
    )
    return render(request, "budget/scheduled_list.html", {
        "active_nav": "scheduled",
        "scheduled": scheduled,
        "today": date.today(),
    })


@feuser_required
def scheduled_create(request):
    feuser = request.feuser
    if request.method == "POST":
        submitted_nonce = request.POST.get("form_nonce", "")
        session_nonce = request.session.pop("scheduled_create_nonce", None)
        if not session_nonce or submitted_nonce != session_nonce:
            return redirect("budget:scheduled_list")

        form = ScheduledExpenseForm(request.POST, feuser=feuser)
        buddy = _parse_buddy_post(request.POST, feuser)
        if form.is_valid() and (buddy is None or buddy["valid"]):
            scheduled_service.save_new_scheduled(feuser, form.save(commit=False), form.cleaned_data["tags"], buddy)
            return redirect("budget:scheduled_list")
        elif buddy and buddy.get("type_conflict"):
            messages.error(request, BUDDY_TYPE_CONFLICT_MSG)
    else:
        form = ScheduledExpenseForm(
            feuser=feuser,
            initial={"type": "expense", "default_auto_settle_on_due_date": True, "notify": True},
        )

    form_nonce = secrets.token_hex(32)
    request.session["scheduled_create_nonce"] = form_nonce

    if request.method == "POST":
        buddy_render_ctx = _buddy_render_context_from_post(buddy, feuser)
    else:
        buddy_render_ctx = {
            "is_buddy_expense": False,
            "existing_mode": "single",
            "existing_upfront_type": "me",
            "existing_upfront_id": feuser.pk,
            "existing_spendings_json": "[]",
            "existing_group_id": None,
        }

    return render(request, "budget/scheduled_form.html", {
        "active_nav": "scheduled",
        "form": form,
        "form_nonce": form_nonce,
        **buddy_render_ctx,
        **_buddy_context(feuser),
    })


@feuser_required
def scheduled_edit(request, uid):
    feuser = request.feuser
    obj = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=feuser)
    if request.method == "POST":
        confirm_a = request.POST.get("confirm_modify_schedule") == "on"
        confirm_b = request.POST.get("confirm_modify_schedule_window") == "on"

        post_data = request.POST.copy()
        # validate unconfirmed schedule fields against their stored values
        if not confirm_a:
            post_data["repeat_every_factor"] = obj.repeat_every_factor
            post_data["repeat_every_unit"] = obj.repeat_every_unit
        if not confirm_b:
            post_data["repeat_base_date"] = obj.repeat_base_date
            post_data["end_on"] = obj.end_on

        form = ScheduledExpenseForm(post_data, instance=obj, feuser=feuser)
        buddy = _parse_buddy_post(request.POST, feuser)
        if form.is_valid() and (buddy is None or buddy["valid"]):
            scheduled_service.update_scheduled(
                feuser, form.save(commit=False), form.cleaned_data["tags"], buddy,
                confirm_schedule=confirm_a, confirm_window=confirm_b,
            )
            return redirect("budget:scheduled_list")
        elif buddy and buddy.get("type_conflict"):
            messages.error(request, BUDDY_TYPE_CONFLICT_MSG)
    else:
        form = ScheduledExpenseForm(instance=obj, feuser=feuser)

    if request.method == "POST":
        buddy_render_ctx = _buddy_render_context_from_post(buddy, feuser)
    else:
        buddy_render_ctx = _existing_assignment_ctx(obj)

    return render(request, "budget/scheduled_form.html", {
        "active_nav": "scheduled",
        "form": form,
        "scheduled": obj,
        "current_financial_year": current_financial_month(feuser.month_start_day, feuser.month_start_prev)[0],
        **buddy_render_ctx,
        **_buddy_context(feuser),
    })


@feuser_required
@require_POST
def scheduled_delete(request, uid):
    obj = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=request.feuser)
    obj.delete()
    return redirect("budget:scheduled_list")


@feuser_required
@require_POST
def scheduled_clone(request, uid):
    original = scheduled_service.clone_scheduled(
        get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=request.feuser)
    )
    return redirect("budget:scheduled_edit", uid=original.pk)


def _assignment_label(expense):
    """Human-readable assignment label for an expense (used in the update modal)."""
    if expense.project:
        return f"Shared in {expense.project.name}"
    spendings = list(expense.buddy_spendings.all())
    if not spendings:
        return "Personal"
    names = []
    for bs in spendings:
        if bs.participant_feuser_id:
            full = f"{bs.participant_feuser.first_name} {bs.participant_feuser.last_name}".strip()
            names.append(full or bs.participant_feuser.email)
        elif bs.participant_dummy_id:
            names.append(bs.participant_dummy.display_name)
    if names:
        return "Shared with " + ", ".join(names)
    return "Shared"


@feuser_required
def scheduled_update_expenses_api(request, uid):
    """GET: list expenses for current financial year. POST: apply scheduled fields to selected expenses."""
    feuser = request.feuser
    scheduled = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=feuser)

    if request.method == "GET":
        expenses = (
            scheduled_service.current_year_expenses(feuser, scheduled)
            .select_related("project", "upfront_payee_dummy")
            .prefetch_related(
                "buddy_spendings__participant_feuser",
                "buddy_spendings__participant_dummy",
            )
            .order_by("date_due")
        )
        data = []
        for e in expenses:
            data.append({
                "id": e.uid,
                "date_due": e.date_due.strftime("%Y-%m-%d") if e.date_due else None,
                "value": str(e.value),
                "assignment": _assignment_label(e),
                "settled": e.settled,
            })
        return JsonResponse({"expenses": data, "currency": feuser.currency})

    if request.method == "POST":
        body = json.loads(request.body)
        expense_ids = body.get("expense_ids", [])
        if not expense_ids:
            return JsonResponse({"ok": True, "updated": 0})
        updated = scheduled_service.apply_to_expenses(feuser, scheduled, expense_ids)
        return JsonResponse({"ok": True, "updated": updated})

    return HttpResponseNotAllowed(["GET", "POST"])
