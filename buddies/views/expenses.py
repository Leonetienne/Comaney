from django.contrib import messages as django_messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from budget.models import Expense
from ..models import Project, BuddyGroup, BuddySpending
from ..services import BuddyEmailService, BuddyLifecycleService


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
        BuddyLifecycleService.approve_expense(expense)
        django_messages.success(request, "Expense confirmed.")
        if expense.project_id:
            return redirect("projects:project_detail", project_id=expense.project_id)
        return redirect("budget:expenses_list")
    approve_url = reverse("buddies:review_expense_as_owner", args=[expense_id])
    reject_url = reverse("buddies:reject_expense", args=[expense_id])
    return render(request, "buddies/confirm_settlement.html", {
        "active_nav": "buddies",
        "expense": expense,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "page_title": "Review shared expense",
        "confirm_question": "Did you actually pay for this expense upfront? Confirming accepts it into the group.",
        "approve_label": "Yes, I paid this",
        "reject_label": "I did not pay this",
        "reject_confirm_text": "Reject this expense? Your participation will be removed and shares redistributed.",
    })


@feuser_required
@require_POST
def approve_expense(request, expense_id):
    expense = get_object_or_404(Expense, uid=expense_id, owning_feuser=request.feuser, buddy_approved=False, is_buddies_settlement=False)
    BuddyLifecycleService.approve_expense(expense)
    return redirect("budget:expenses_list")


@feuser_required
@require_POST
def reject_expense(request, expense_id):
    expense = get_object_or_404(Expense, uid=expense_id, owning_feuser=request.feuser, buddy_approved=False)
    BuddyLifecycleService.reject_expense(expense, request.feuser)
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
        from datetime import date as _date
        from budget.expense_factory import create_expense as _create_expense
        from budget.models import TransactionType

        creditor = request.feuser
        bs_row = expense.buddy_spendings.filter(participant_feuser=creditor).first()
        income_amount = expense.value * (bs_row.share_percent / 100) if bs_row else expense.value

        if expense.is_dummy and expense.upfront_payee_dummy_id:
            debtor_label = expense.upfront_payee_dummy.display_name + " (offline member)"
        else:
            debtor_label = f"{expense.owning_feuser.first_name} {expense.owning_feuser.last_name}".strip() or expense.owning_feuser.email

        _create_expense(
            owning_feuser=creditor,
            title=f"Settlement received from {debtor_label}",
            type=TransactionType.INCOME,
            value=income_amount,
            date_due=_date.today(),
            settled=True,
            notify=False,
            buddy_approved=True,
        )

        BuddyLifecycleService.approve_expense(expense)
        BuddyEmailService.send_settlement_approved_notification(
            expense, creditor, expense.owning_feuser
        )
        if expense.project_id and expense.project:
            expense.project.update_lastmod()
        django_messages.success(request, "Settlement confirmed. Thank you!")
        if expense.project_id:
            return redirect("projects:project_detail", project_id=expense.project_id)
        return redirect("buddies:buddy_summary")
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
    expense = get_object_or_404(
        Expense,
        uid=expense_id,
        buddy_approved=False,
        is_buddies_settlement=True,
        buddy_spendings__participant_feuser=request.feuser,
    )
    debtor = expense.owning_feuser
    creditor = request.feuser
    group_id = expense.project_id
    _proj = expense.project if expense.project_id else None
    BuddyEmailService.send_settlement_rejection_notification(expense, creditor, debtor)
    expense.delete()
    if _proj:
        _proj.update_lastmod()
    django_messages.warning(request, "Settlement rejected. The debtor has been notified.")
    if group_id:
        return redirect("projects:project_detail", project_id=group_id)
    return redirect("buddies:buddy_summary")


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
        BuddyLifecycleService.approve_expense(expense)
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
    feuser = request.feuser
    group = get_object_or_404(Project, uid=group_id, admin_feuser=feuser)
    expense = get_object_or_404(
        Expense,
        uid=expense_id,
        project=group,
        buddy_approved=False,
    )
    has_dummy_upfront = expense.is_dummy and expense.upfront_payee_dummy_id and not expense.is_buddies_settlement
    has_dummy_creditor = expense.buddy_spendings.filter(
        participant_dummy__owning_group=group
    ).exists()
    if not has_dummy_creditor and not has_dummy_upfront:
        django_messages.error(request, "This expense does not involve an offline member of this group.")
        return redirect("projects:project_detail", project_id=group_id)
    debtor = expense.owning_feuser
    if has_dummy_upfront:
        expense.delete()
        django_messages.warning(request, "Expense rejected and removed.")
        return redirect("projects:project_detail", project_id=group_id)
    BuddyEmailService.send_settlement_rejection_notification(expense, feuser, debtor)
    expense.delete()
    django_messages.warning(request, "Settlement rejected. The debtor has been notified.")
    return redirect("projects:project_detail", project_id=group_id)


def _participant_set_approval(request, expense_id, new_state):
    from django.utils import timezone
    from django.http import HttpResponseForbidden
    feuser = request.feuser
    expense = get_object_or_404(
        Expense,
        uid=expense_id,
        is_buddies_settlement=False,
        buddy_spendings__participant_feuser=feuser,
    )
    bs = expense.buddy_spendings.filter(participant_feuser=feuser).first()
    if not bs:
        return redirect("buddies:buddy_summary")

    if bs.consent_locked:
        return HttpResponseForbidden("Decision is locked after 24 hours.")

    if bs.approval_state != new_state:
        update_fields = ["approval_state"]
        if bs.consent_set_at is None:
            bs.consent_set_at = timezone.now()
            update_fields.append("consent_set_at")
        bs.approval_state = new_state
        bs.last_mod = timezone.now()
        update_fields.append("last_mod")
        bs.save(update_fields=update_fields)
        BuddyEmailService.send_participant_approval_notification(expense, feuser, new_state)

    back = request.POST.get("back") or request.GET.get("back")
    if back:
        return redirect(back)
    if expense.project_id:
        return redirect("projects:project_detail", project_id=expense.project_id)
    return redirect("buddies:buddy_summary")


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
    feuser = request.feuser
    group = get_object_or_404(Project, uid=group_id, members__feuser=feuser)
    is_admin = group.admin_feuser_id == feuser.pk
    dummy_pks_in_group = {
        m.dummy_id for m in group.members.all() if m.dummy_id
    }

    try:
        expense = Expense.objects.get(uid=expense_id, project=group)
    except Expense.DoesNotExist:
        django_messages.error(request, "Expense not found.")
        return redirect("projects:project_detail", project_id=group_id)

    is_feuser_direct_owner = expense.owning_feuser_id == feuser.pk and not expense.is_dummy
    is_dummy_exp_in_group = (
        expense.is_dummy
        and expense.upfront_payee_dummy_id
        and expense.upfront_payee_dummy_id in dummy_pks_in_group
    )
    # Admin can only manage their OWN settlements to group dummies (is_feuser_direct_owner).
    # Another member's settlement to a group dummy is not the admin's to delete.
    is_settlement_to_group_dummy = (
        expense.is_buddies_settlement
        and is_admin
        and is_feuser_direct_owner
        and expense.buddy_spendings.filter(
            participant_dummy_id__in=dummy_pks_in_group
        ).exists()
    )

    if group.archived:
        django_messages.error(request, "Cannot delete expenses from an archived project.")
        return redirect("projects:project_detail", project_id=group_id)

    if not (is_feuser_direct_owner or (is_admin and is_dummy_exp_in_group) or is_settlement_to_group_dummy):
        django_messages.error(request, "You do not have permission to delete this expense.")
        return redirect("projects:project_detail", project_id=group_id)

    # Once a group settlement is approved, only specific admin-owned paths may delete it:
    # - admin's own settlement to a group dummy (is_settlement_to_group_dummy)
    # - admin managing an all-dummy expense with no real feuser creditor (G5)
    # Non-admin debtors are always locked out of approved group settlements.
    if expense.is_buddies_settlement and expense.buddy_approved:
        has_real_creditor = expense.buddy_spendings.filter(participant_feuser__isnull=False).exists()
        can_delete_approved = (
            is_settlement_to_group_dummy
            or (is_admin and is_dummy_exp_in_group and not has_real_creditor)
        )
        if not can_delete_approved:
            django_messages.error(request, "An approved settlement cannot be deleted.")
            return redirect("projects:project_detail", project_id=group_id)

    # Notify the real-user creditor when their unapproved settlement is deleted
    if expense.is_buddies_settlement and not expense.buddy_approved and not is_settlement_to_group_dummy:
        bs = expense.buddy_spendings.select_related("participant_feuser").filter(
            participant_feuser__isnull=False
        ).first()
        if bs:
            BuddyEmailService.send_settlement_cancelled_notification(
                expense, bs.participant_feuser
            )

    expense.delete()
    group.update_lastmod()
    django_messages.success(request, "Expense deleted.")
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
@require_POST
def group_expense_unlink(request, group_id, expense_id):
    feuser = request.feuser
    group = get_object_or_404(Project, uid=group_id, members__feuser=feuser)
    is_admin = group.admin_feuser_id == feuser.pk

    try:
        expense = Expense.objects.get(uid=expense_id, project=group)
    except Expense.DoesNotExist:
        django_messages.error(request, "Expense not found.")
        return redirect("projects:project_detail", project_id=group_id)

    if group.archived:
        django_messages.error(request, "Cannot unlink expenses from an archived project.")
        return redirect("projects:project_detail", project_id=group_id)

    is_feuser_direct_owner = expense.owning_feuser_id == feuser.pk and not expense.is_dummy
    if not (is_feuser_direct_owner or is_admin):
        django_messages.error(request, "You do not have permission to unlink this expense.")
        return redirect("projects:project_detail", project_id=group_id)

    notify_feusers = set()
    if is_admin and not is_feuser_direct_owner:
        if not expense.is_dummy:
            notify_feusers.add(expense.owning_feuser)
        for bs in expense.buddy_spendings.select_related("participant_feuser").all():
            if bs.participant_feuser_id and bs.participant_feuser_id != feuser.pk:
                notify_feusers.add(bs.participant_feuser)

    expense.buddy_spendings.all().delete()
    expense.project = None
    expense.is_dummy = False
    expense.upfront_payee_dummy = None
    expense.buddy_approved = True
    expense.save()

    for fu in notify_feusers:
        BuddyEmailService.send_expense_unlinked_notification(
            expense=expense,
            admin_feuser=feuser,
            group=group,
            notify_feuser=fu,
            is_owner=(fu.pk == expense.owning_feuser_id),
        )

    django_messages.success(request, "Expense unlinked from the group. It remains in the owner's expense list.")
    return redirect("projects:project_detail", project_id=group_id)
