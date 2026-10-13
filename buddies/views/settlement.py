from django.contrib import messages as django_messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from ..services import BuddySettlementService, settlement_actions
from ..services.settlement_actions import SettlementError


@feuser_required
@require_POST
def settle_direct(request):
    selected = request.POST.getlist("settle")
    if selected:
        count = BuddySettlementService.create_direct_settlements(request.feuser, selected)
        if count:
            django_messages.success(request, f"{count} settlement record{'s' if count != 1 else ''} created.")
    return redirect("buddies:contact_summary")


@feuser_required
@require_POST
def settle_direct_individual(request, contact_key):
    return _settle_with_contact(request, contact_key)


@feuser_required
@require_POST
def settle_direct_freeform(request):
    """Single-form personal settlement: debtor_key and creditor_key come from POST body."""
    return _settle_with_contact(
        request, request.POST.get("creditor_key", "").strip(), request.POST.get("debtor_key", "").strip(),
    )


def _settle_with_contact(request, creditor_key, debtor_key=None):
    try:
        amount = settlement_actions.parse_amount(request.POST.get("amount", "0"))
        django_messages.success(
            request, settlement_actions.settle_with_contact(request.feuser, creditor_key, amount, debtor_key),
        )
    except SettlementError as exc:
        django_messages.error(request, str(exc))
    return redirect("buddies:contact_summary")


@feuser_required
@require_POST
def group_settle_individual(request, group_id):
    from ..models import Project
    group = get_object_or_404(Project, uid=group_id, members__feuser=request.feuser)
    try:
        amount = settlement_actions.parse_amount(request.POST.get("amount", "0"))
        django_messages.success(request, settlement_actions.settle_in_project(
            request.feuser, group,
            request.POST.get("debtor_key", "").strip(), request.POST.get("creditor_key", "").strip(), amount,
        ))
    except SettlementError as exc:
        django_messages.error(request, str(exc))
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
@require_POST
def group_settle_all(request, group_id):
    from ..models import Project
    feuser = request.feuser
    group = get_object_or_404(Project, uid=group_id, admin_feuser=feuser)
    try:
        count = settlement_actions.settle_project_all(feuser, group)
    except SettlementError as exc:
        django_messages.error(request, str(exc))
        return redirect("projects:project_detail", project_id=group_id)
    if count:
        django_messages.success(request, f"{count} settlement record{'s' if count != 1 else ''} created. Emails have been sent to all members.")
    else:
        django_messages.info(request, "No outstanding debts to settle.")
    return redirect("projects:project_detail", project_id=group_id)
