import json
import secrets
from datetime import date

from django.core.management import call_command
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..date_utils import current_financial_month, financial_year_range
from ..decorators import feuser_required
from ..forms import ScheduledExpenseForm
from ..models import Expense, ScheduledExpense
from .expenses import _buddy_context, _parse_buddy_post


def _generate_and_notify(scheduled: ScheduledExpense, feuser) -> None:
    """Run generation for feuser, then notify participants of any newly created expenses."""
    from buddies.services import BuddyEmailService

    existing_ids = set(
        Expense.objects.filter(source_scheduled=scheduled)
        .values_list("uid", flat=True)
    )
    call_command("generate_scheduled_expenses", user=feuser.email)
    new_expenses = (
        Expense.objects
        .filter(source_scheduled=scheduled)
        .exclude(uid__in=existing_ids)
        .prefetch_related(
            "buddy_spendings__participant_feuser",
            "buddy_spendings__participant_dummy",
        )
    )
    for expense in new_expenses:
        BuddyEmailService.notify_expense_created(expense, feuser)


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
            _generate_and_notify(obj, feuser)
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
            _generate_and_notify(obj, feuser)
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

    year = current_financial_month(feuser.month_start_day, feuser.month_start_prev)[0]
    start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)

    if request.method == "GET":
        expenses = (
            Expense.objects
            .filter(source_scheduled=scheduled, owning_feuser=feuser,
                    date_due__gte=start, date_due__lte=end)
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
            })
        return JsonResponse({"expenses": data, "currency": feuser.currency})

    if request.method == "POST":
        from buddies.services import BuddyEmailService, BuddyExpenseService

        body = json.loads(request.body)
        expense_ids = body.get("expense_ids", [])
        if not expense_ids:
            return JsonResponse({"ok": True, "updated": 0})

        expenses = list(
            Expense.objects.filter(
                uid__in=expense_ids,
                source_scheduled=scheduled,
                owning_feuser=feuser,
            ).select_related("project")
        )

        mode = scheduled.assign_buddy_mode
        upfront_type = scheduled.assign_upfront_type
        spendings = json.loads(scheduled.assign_spendings_json or "[]")
        tags = list(scheduled.tags.all())

        for expense in expenses:
            # Snapshot state before any changes for notification diffing
            old_title = expense.title
            old_value = expense.value
            old_participants = {
                bs.participant_feuser_id: (bs.participant_feuser, bs.share_percent)
                for bs in expense.buddy_spendings
                .select_related("participant_feuser")
                .filter(participant_feuser__isnull=False)
            }

            expense.title = scheduled.title
            expense.payee = scheduled.payee
            expense.note = scheduled.note
            expense.category = scheduled.category
            expense.type = scheduled.type
            expense.value = scheduled.value
            expense.auto_settle_on_due_date = scheduled.default_auto_settle_on_due_date
            expense.notify = scheduled.notify

            if not mode:
                expense.is_dummy = False
                expense.upfront_payee_dummy = None
                expense.project = None
            elif mode == "group":
                expense.is_dummy = False
                expense.upfront_payee_dummy = None
                expense.project = scheduled.assign_project
            elif mode == "single":
                expense.project = None
                if upfront_type == "dummy" and scheduled.assign_upfront_dummy:
                    expense.is_dummy = True
                    expense.upfront_payee_dummy = scheduled.assign_upfront_dummy
                else:
                    expense.is_dummy = False
                    expense.upfront_payee_dummy = None

            expense.save()
            expense.tags.set(tags)
            BuddyExpenseService.set_buddy_spendings(expense, spendings)
            if expense.project:
                expense.project.update_lastmod()

            BuddyEmailService.notify_expense_updated(
                expense, feuser, old_title, old_value, old_participants
            )

        return JsonResponse({"ok": True, "updated": len(expenses)})

    return HttpResponseNotAllowed(["GET", "POST"])
