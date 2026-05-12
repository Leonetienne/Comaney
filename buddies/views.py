import json
from decimal import Decimal

from django.contrib import messages as django_messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from feusers.models import FeUser

from .models import BuddyInvite, BuddyLink, BuddySpending, DummyMergeInvite, DummyUser
from .services import (
    BuddyEmailService,
    BuddyExpenseService,
    BuddyLifecycleService,
    BuddyQueryService,
    _display_name,
)


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

@feuser_required
def buddies_page(request):
    feuser = request.feuser
    debts = BuddyQueryService.get_all_debts(feuser)
    shared = BuddyQueryService.shared_expenses(feuser)
    pending_in = BuddyQueryService.pending_invites_incoming(feuser)
    pending_out = BuddyQueryService.pending_invites_outgoing(feuser)
    merge_in = BuddyQueryService.pending_merge_invites_incoming(feuser)

    return render(request, "buddies/buddies_page.html", {
        "active_nav": "buddies",
        "debts": debts,
        "shared_expenses": shared,
        "pending_invites_in": pending_in,
        "pending_invites_out": pending_out,
        "merge_invites_in": merge_in,
    })


# ---------------------------------------------------------------------------
# Dummy management
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def add_dummy(request):
    name = request.POST.get("display_name", "").strip()
    if not name:
        return redirect("buddies:buddies_page")
    BuddyLifecycleService.add_dummy(request.feuser, name)
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def kick_dummy(request, dummy_id):
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_feuser=request.feuser)
    accepted = request.POST.get("debt_warning_accepted") == "yes"
    result = BuddyLifecycleService.kick_dummy(request.feuser, dummy, has_debt_warning_accepted=accepted)
    if "debt_warning" in result:
        return render(request, "buddies/kick_debt_warning.html", {
            "active_nav": "buddies",
            "buddy_name": dummy.display_name,
            "net_debt": result["debt_warning"],
            "confirm_url": request.path,
            "back_url": "/buddies/",
        })
    return redirect("buddies:buddies_page")


# ---------------------------------------------------------------------------
# Actual buddy invitation
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def invite_actual(request):
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("buddies:buddies_page")

    outcome, obj = BuddyLifecycleService.invite_actual(request.feuser, email)
    return redirect("buddies:buddies_page")


@feuser_required
def view_invite(request, token):
    """Landing page for an invite recipient."""
    try:
        invite = BuddyInvite.objects.select_related("inviter").get(token=token)
    except BuddyInvite.DoesNotExist:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if not invite.is_valid():
        invite.delete()
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if request.feuser.email.lower() != invite.invitee_email.lower():
        return render(request, "buddies/invite_wrong_account.html", {
            "active_nav": "buddies",
            "invite": invite,
        })

    return render(request, "buddies/invite_view.html", {
        "active_nav": "buddies",
        "invite": invite,
        "inviter_name": _display_name(invite.inviter),
    })


@feuser_required
@require_POST
def accept_invite(request, token):
    link = BuddyLifecycleService.accept_invite(token, request.feuser)
    if link is None:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def decline_invite(request, token):
    BuddyLifecycleService.decline_invite(token, request.feuser)
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def revoke_invite(request, token):
    BuddyLifecycleService.revoke_invite(token, request.feuser)
    return redirect("buddies:buddies_page")


# ---------------------------------------------------------------------------
# Actual buddy kick
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def kick_actual(request, link_id):
    link = get_object_or_404(BuddyLink, uid=link_id)
    if link.user_a_id != request.feuser.pk and link.user_b_id != request.feuser.pk:
        return redirect("buddies:buddies_page")

    other = link.other(request.feuser)
    accepted = request.POST.get("debt_warning_accepted") == "yes"
    result = BuddyLifecycleService.kick_actual(
        request.feuser, other, has_debt_warning_accepted=accepted
    )
    if "debt_warning" in result:
        return render(request, "buddies/kick_debt_warning.html", {
            "active_nav": "buddies",
            "buddy_name": _display_name(other),
            "net_debt": result["debt_warning"],
            "confirm_url": request.path,
            "back_url": "/buddies/",
        })
    return redirect("buddies:buddies_page")


# ---------------------------------------------------------------------------
# Merge invite
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def send_merge_invite(request, dummy_id):
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_feuser=request.feuser)
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("buddies:buddies_page")
    BuddyLifecycleService.send_merge_invite(request.feuser, dummy, email)
    return redirect("buddies:buddies_page")


@feuser_required
def view_merge_invite(request, token):
    try:
        invite = DummyMergeInvite.objects.select_related(
            "inviting_feuser", "dummy"
        ).get(token=token)
    except DummyMergeInvite.DoesNotExist:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if not invite.is_valid():
        invite.delete()
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if invite.invited_feuser_id != request.feuser.pk:
        return render(request, "buddies/invite_wrong_account.html", {
            "active_nav": "buddies",
            "invite": invite,
        })

    return render(request, "buddies/merge_view.html", {
        "active_nav": "buddies",
        "invite": invite,
        "inviting_name": _display_name(invite.inviting_feuser),
    })


@feuser_required
@require_POST
def accept_merge(request, token):
    ok = BuddyLifecycleService.accept_merge(token, request.feuser)
    if not ok:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def decline_merge(request, token):
    try:
        invite = DummyMergeInvite.objects.get(
            token=token,
            invited_feuser=request.feuser,
        )
        invite.delete()
    except DummyMergeInvite.DoesNotExist:
        pass
    return redirect("buddies:buddies_page")


# ---------------------------------------------------------------------------
# Expense approval / rejection
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def approve_expense(request, expense_id):
    from budget.models import Expense
    expense = get_object_or_404(Expense, uid=expense_id, owning_feuser=request.feuser, buddy_approved=False)
    BuddyLifecycleService.approve_expense(expense)
    return redirect("budget:expenses_list")


@feuser_required
@require_POST
def reject_expense(request, expense_id):
    from budget.models import Expense
    expense = get_object_or_404(Expense, uid=expense_id, owning_feuser=request.feuser, buddy_approved=False)
    BuddyLifecycleService.reject_expense(expense, request.feuser)
    return redirect("budget:expenses_list")
