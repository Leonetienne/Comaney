from django.contrib import messages as django_messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from budget.models import Expense
from ..models import Project, BuddySpending
from ..services import approvals


def _build_expense_preview(expense, viewer):
    """Payer + participant share rows for the expense review/preview screen."""
    from decimal import Decimal

    offline_label = "(offline member)" if expense.project_id else "(offline contact)"
    fu = expense.owning_feuser
    payer_name = f"{fu.first_name} {fu.last_name}".strip() or fu.email

    participant_shares = []
    total_pct = Decimal("0")
    for bs in expense.buddy_spendings.all():
        if bs.participant_feuser_id:
            pf = bs.participant_feuser
            name = f"{pf.first_name} {pf.last_name}".strip() or pf.email
            is_me = pf.pk == viewer.pk
        else:
            name = f"{bs.participant_dummy.display_name} {offline_label}"
            is_me = False
        total_pct += bs.share_percent
        participant_shares.append({
            "name": name,
            "is_me": is_me,
            "percent": bs.share_percent,
            "amount": expense.value * bs.share_percent / 100,
        })

    payer_pct = Decimal("100") - total_pct
    return {
        "currency": fu.currency,
        "note": expense.note,
        "payer_name": payer_name,
        "payer_is_me": fu.pk == viewer.pk,
        "payer_percent": payer_pct,
        "payer_amount": expense.value * payer_pct / 100,
        "participant_shares": participant_shares,
    }


@feuser_required
def review_expense_as_owner(request, expense_id):
    """
    Upfront-payer confirmation. GET shows a review page; POST confirms they paid.
    The email link points here (GET).
    """
    expense = get_object_or_404(
        Expense,
        uid=expense_id,
        owning_feuser=request.feuser,
        buddy_approved=False,
        is_buddies_settlement=False,
        is_dummy=False,
    )
    if request.method == "POST":
        approvals.confirm_paid(request.feuser, expense.uid)
        django_messages.success(request, "Expense confirmed.")
        if expense.project_id:
            return redirect("projects:project_detail", project_id=expense.project_id)
        return redirect("budget:expenses_list")
    approve_url = reverse("buddies:review_expense_as_owner", args=[expense_id])
    reject_url = reverse("buddies:reject_expense", args=[expense_id])
    return render(request, "buddies/confirm_settlement.html", {
        "active_nav": "buddies",
        "expense": expense,
        "preview": _build_expense_preview(expense, request.feuser),
        "approve_url": approve_url,
        "reject_url": reject_url,
        "page_title": "Review shared expense",
        "confirm_question": "Did you actually pay for this expense? Confirming accepts it into the group.",
        "approve_label": "Yes, I paid this",
        "reject_label": "I did not pay this",
        "reject_confirm_text": "Reject this expense? Your participation will be removed and shares redistributed.",
    })


@feuser_required
@require_POST
def approve_expense(request, expense_id):
    try:
        approvals.confirm_paid(request.feuser, expense_id)
    except approvals.NotFound:
        raise Http404
    return redirect("budget:expenses_list")


@feuser_required
@require_POST
def reject_expense(request, expense_id):
    try:
        approvals.reject_paid(request.feuser, expense_id)
    except approvals.NotFound:
        raise Http404
    return redirect("budget:expenses_list")


@feuser_required
def approve_settlement_as_creditor(request, expense_id):
    """
    Creditor-side settlement approval. GET shows a confirmation page;
    POST confirms receipt. The email link points here (GET).
    """
    expense = get_object_or_404(
        Expense,
        uid=expense_id,
        buddy_approved=False,
        is_buddies_settlement=True,
        buddy_spendings__participant_feuser=request.feuser,
    )
    if request.method == "POST":
        approvals.confirm_settlement(request.feuser, expense.uid)
        django_messages.success(request, "Settlement confirmed. Thank you!")
        if expense.project_id:
            return redirect("projects:project_detail", project_id=expense.project_id)
        return redirect("buddies:contact_summary")
    return render(request, "buddies/confirm_settlement.html", {
        "active_nav": "buddies",
        "expense": expense,
    })


@feuser_required
@require_POST
def reject_settlement_as_creditor(request, expense_id):
    """
    Creditor declares they did not receive the payment. Deletes the debtor's settlement
    expense and emails the debtor to notify them.
    """
    try:
        project = approvals.reject_settlement(request.feuser, expense_id)
    except approvals.NotFound:
        raise Http404
    group_id = project.uid if project else None
    django_messages.warning(request, "Settlement rejected. The debtor has been notified.")
    if group_id:
        return redirect("projects:project_detail", project_id=group_id)
    return redirect("buddies:contact_summary")


@feuser_required
def admin_approve_dummy_settlement(request, group_id, expense_id):
    """Admin reviews and confirms a settlement involving a dummy creditor in their group."""
    feuser = request.feuser
    group = get_object_or_404(Project, uid=group_id, admin_feuser=feuser)
    expense = get_object_or_404(
        Expense,
        uid=expense_id,
        project=group,
        buddy_approved=False,
    )
    has_dummy_upfront = expense.is_dummy and expense.upfront_payee_dummy_id
    has_dummy_creditor = expense.buddy_spendings.filter(
        participant_dummy__owning_group=group
    ).exists()
    if not (has_dummy_upfront or has_dummy_creditor):
        django_messages.error(request, "This expense does not involve an offline member of this group.")
        return redirect("projects:project_detail", project_id=group_id)
    has_real_feuser_creditor = expense.buddy_spendings.filter(
        participant_feuser__isnull=False
    ).exists()
    if expense.is_buddies_settlement and has_real_feuser_creditor:
        django_messages.error(request, "Only the creditor can confirm this settlement.")
        return redirect("projects:project_detail", project_id=group_id)
    is_dummy_upfront = has_dummy_upfront and not expense.is_buddies_settlement
    if request.method == "POST":
        approvals.admin_confirm(feuser, group_id, expense_id)
        if is_dummy_upfront:
            django_messages.success(request, "Expense confirmed.")
        else:
            django_messages.success(request, "Settlement confirmed. Thank you!")
        return redirect("projects:project_detail", project_id=group_id)
    approve_url = reverse("projects:admin_approve_dummy_settlement", args=[group_id, expense_id])
    reject_url = reverse("projects:admin_reject_dummy_settlement", args=[group_id, expense_id])
    if is_dummy_upfront:
        payer_name = expense.upfront_payee_dummy.display_name + " (offline member)"
        return render(request, "buddies/confirm_settlement.html", {
            "active_nav": "buddies",
            "expense": expense,
            "approve_url": approve_url,
            "reject_url": reject_url,
            "page_title": f"Confirm expense paid by {payer_name}",
            "confirm_question": f"Did {payer_name} actually pay for this expense upfront? Confirming accepts it into the project.",
            "approve_label": "Yes, confirm expense",
            "reject_label": "No, reject this expense",
            "reject_confirm_text": "Reject this expense? It will be removed from the project.",
        })
    dummy_bs = expense.buddy_spendings.filter(
        participant_dummy__owning_group=group
    ).select_related("participant_dummy").first()
    creditor_name = (
        f"{dummy_bs.participant_dummy.display_name} (offline member)" if dummy_bs else None
    )
    return render(request, "buddies/confirm_settlement.html", {
        "active_nav": "buddies",
        "expense": expense,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "creditor_name": creditor_name,
        "confirm_question": f"Did {creditor_name} actually receive this payment?" if creditor_name else None,
    })


@feuser_required
@require_POST
def admin_reject_dummy_settlement(request, group_id, expense_id):
    """Admin rejects a settlement on behalf of a dummy creditor: deletes it and notifies the debtor."""
    try:
        offline_paid = approvals.admin_reject(request.feuser, group_id, expense_id)
    except approvals.NotFound:
        raise Http404
    except approvals.ApprovalError as exc:
        django_messages.error(request, str(exc))
        return redirect("projects:project_detail", project_id=group_id)
    if offline_paid:
        django_messages.warning(request, "Expense rejected and removed.")
    else:
        django_messages.warning(request, "Settlement rejected. The debtor has been notified.")
    return redirect("projects:project_detail", project_id=group_id)


def _participant_set_approval(request, expense_id, new_state):
    from django.http import HttpResponseForbidden, JsonResponse
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    try:
        bs = approvals.set_participant_consent(
            request.feuser, expense_id, new_state == BuddySpending.APPROVAL_APPROVED,
        )
    except approvals.NotFound:
        if is_ajax:
            return JsonResponse({"error": "not_participant"}, status=404)
        return redirect("buddies:contact_summary")
    except approvals.ApprovalError:
        bs = BuddySpending.objects.filter(expense_id=expense_id, participant_feuser=request.feuser).first()
        if is_ajax:
            return JsonResponse(
                {"error": "locked", "approval_state": bs.approval_state, "can_change_consent": False},
                status=403,
            )
        return HttpResponseForbidden("Decision is locked after 24 hours.")
    expense = bs.expense

    if is_ajax:
        return JsonResponse({"approval_state": bs.approval_state, "can_change_consent": bs.can_change_consent})

    back = request.POST.get("back") or request.GET.get("back")
    if back:
        return redirect(back)
    if expense.project_id:
        return redirect("projects:project_detail", project_id=expense.project_id)
    return redirect("buddies:contact_summary")


@feuser_required
def participant_approve(request, expense_id):
    """Record feuser consent as approved. Accepts GET (email) and POST (inline button)."""
    return _participant_set_approval(request, expense_id, BuddySpending.APPROVAL_APPROVED)


@feuser_required
def participant_reject(request, expense_id):
    """Record feuser consent as rejected. Accepts GET (email) and POST (inline button)."""
    return _participant_set_approval(request, expense_id, BuddySpending.APPROVAL_REJECTED)


@feuser_required
@require_POST
def group_expense_delete(request, group_id, expense_id):
    try:
        approvals.delete_project_expense(request.feuser, group_id, expense_id)
    except approvals.ApprovalError as exc:
        django_messages.error(request, str(exc))
        return redirect("projects:project_detail", project_id=group_id)
    django_messages.success(request, "Expense deleted.")
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
@require_POST
def group_expense_unlink(request, group_id, expense_id):
    try:
        approvals.unlink_project_expense(request.feuser, group_id, expense_id)
    except approvals.ApprovalError as exc:
        django_messages.error(request, str(exc))
        return redirect("projects:project_detail", project_id=group_id)
    django_messages.success(request, "Expense unlinked from the group. It remains in the owner's expense list.")
    return redirect("projects:project_detail", project_id=group_id)
