import json
import secrets
from datetime import date

from django.core.management import call_command
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..decorators import feuser_required
from ..forms import ScheduledExpenseForm
from ..models import ScheduledExpense
from .expenses import _buddy_context, _parse_buddy_post


def _apply_assignment(obj: ScheduledExpense, buddy: dict | None) -> None:
    """Write parsed buddy assignment fields onto a ScheduledExpense instance."""
    if not buddy:
        obj.assign_buddy_mode = ''
        obj.assign_upfront_type = 'me'
        obj.assign_upfront_feuser = None
        obj.assign_upfront_dummy = None
        obj.assign_project = None
        obj.assign_spendings_json = '[]'
    else:
        obj.assign_buddy_mode = buddy['mode']
        obj.assign_upfront_type = buddy['upfront_type']
        obj.assign_upfront_feuser = buddy.get('upfront_feuser')
        obj.assign_upfront_dummy = buddy.get('upfront_dummy')
        obj.assign_project = buddy.get('group') if buddy['mode'] == 'group' else None
        obj.assign_spendings_json = json.dumps(buddy.get('spendings', []))


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
            obj = form.save(commit=False)
            obj.owning_feuser = feuser
            _apply_assignment(obj, buddy)
            obj.save()
            form.save_m2m()
            call_command("generate_scheduled_expenses", user=feuser.email)
            return redirect("budget:scheduled_list")
    else:
        form = ScheduledExpenseForm(
            feuser=feuser,
            initial={"type": "expense", "default_auto_settle_on_due_date": True, "notify": True},
        )

    form_nonce = secrets.token_hex(32)
    request.session["scheduled_create_nonce"] = form_nonce

    return render(request, "budget/scheduled_form.html", {
        "active_nav": "scheduled",
        "form": form,
        "form_nonce": form_nonce,
        "is_buddy_expense": False,
        "existing_mode": "single",
        "existing_upfront_type": "me",
        "existing_upfront_id": feuser.pk,
        "existing_spendings_json": "[]",
        "existing_group_id": None,
        **_buddy_context(feuser),
    })


@feuser_required
def scheduled_edit(request, uid):
    feuser = request.feuser
    obj = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=feuser)
    if request.method == "POST":
        form = ScheduledExpenseForm(request.POST, instance=obj, feuser=feuser)
        buddy = _parse_buddy_post(request.POST, feuser)
        if form.is_valid() and (buddy is None or buddy["valid"]):
            obj = form.save(commit=False)
            _apply_assignment(obj, buddy)
            obj.save()
            form.save_m2m()
            call_command("generate_scheduled_expenses", user=feuser.email)
            return redirect("budget:scheduled_list")
    else:
        form = ScheduledExpenseForm(instance=obj, feuser=feuser)

    return render(request, "budget/scheduled_form.html", {
        "active_nav": "scheduled",
        "form": form,
        "scheduled": obj,
        **_existing_assignment_ctx(obj),
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
    original = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=request.feuser)
    tags = list(original.tags.all())
    original.pk = None
    original.title = f"CLONE - {original.title}"
    original.save()
    original.tags.set(tags)
    return redirect("budget:scheduled_edit", uid=original.pk)
