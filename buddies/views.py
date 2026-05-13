import json
from decimal import Decimal

from django.contrib import messages as django_messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from feusers.models import FeUser

from .models import BuddyGroupInvite, BuddyGroupMember, BuddyInvite, BuddyLink, BuddySpending, DummyMergeInvite, DummyUser
from .services import (
    BuddyEmailService,
    BuddyExpenseService,
    BuddyGroupService,
    BuddyLifecycleService,
    BuddyQueryService,
    _display_name,
)


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

@feuser_required
def buddies_page(request):
    return redirect("buddies:my_buddies")


@feuser_required
def my_buddies_page(request):
    feuser = request.feuser
    unified_debts = BuddyQueryService.get_all_debts_unified(feuser)
    my_groups = BuddyQueryService.get_groups_for_feuser(feuser)
    pending_in = BuddyQueryService.pending_invites_incoming(feuser)
    pending_out = BuddyQueryService.pending_invites_outgoing(feuser)
    merge_in = BuddyQueryService.pending_merge_invites_incoming(feuser)
    group_invites_in = BuddyQueryService.pending_group_invites_incoming(feuser)

    return render(request, "buddies/my_buddies.html", {
        "active_nav": "my_buddies",
        "unified_debts": unified_debts,
        "my_groups": my_groups,
        "pending_invites_in": pending_in,
        "pending_invites_out": pending_out,
        "merge_invites_in": merge_in,
        "group_invites_in": group_invites_in,
    })


def _debts_to_json(unified_debts) -> str:
    rows = []
    for info in unified_debts:
        rows.append({"name": info["display_name"], "net": float(info["net"])})
    return json.dumps(rows)


@feuser_required
def buddy_summary_page(request):
    feuser = request.feuser
    unified_debts = BuddyQueryService.get_all_debts_unified(feuser)  # direct buddies only
    all_shared = BuddyQueryService.shared_expenses(feuser)
    direct_expenses = all_shared.filter(buddy_group__isnull=True)
    my_groups_summary = BuddyQueryService.get_group_summaries_for_feuser(feuser)

    return render(request, "buddies/buddy_summary.html", {
        "active_nav": "buddy_summary",
        "direct_expenses": direct_expenses,
        "my_groups_summary": my_groups_summary,
        "debts_json": _debts_to_json(unified_debts),
    })


# ---------------------------------------------------------------------------
# Dummy management (personal)
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
    BuddyLifecycleService.kick_dummy(request.feuser, dummy, has_debt_warning_accepted=True)
    return redirect("buddies:buddies_page")


# ---------------------------------------------------------------------------
# Actual buddy invitation
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def invite_actual(request):
    from django.conf import settings as django_settings
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("buddies:my_buddies")

    outcome, obj = BuddyLifecycleService.invite_actual(request.feuser, email)
    if outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated for this instance. Give this link to your friend: {site_url}/register/")
    elif outcome == "onboarding":
        django_messages.success(request, f"A registration invitation has been sent to {email}. They will be linked as your buddy once they sign up.")
    return redirect("buddies:my_buddies")


@feuser_required
def view_invite(request, token):
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
    BuddyLifecycleService.kick_actual(request.feuser, other, has_debt_warning_accepted=True)
    return redirect("buddies:buddies_page")


# ---------------------------------------------------------------------------
# Merge invite (personal dummy)
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def send_merge_invite(request, dummy_id):
    from django.conf import settings as django_settings
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_feuser=request.feuser)
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("buddies:my_buddies")
    outcome, obj = BuddyLifecycleService.send_merge_invite(request.feuser, dummy, email)
    if outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated for this instance. Give this link to your friend: {site_url}/register/")
    elif outcome == "onboarding":
        django_messages.success(request, f"A registration invitation has been sent to {email}. They will be linked once they sign up.")
    return redirect("buddies:my_buddies")


@feuser_required
def view_merge_invite(request, token):
    try:
        invite = DummyMergeInvite.objects.select_related(
            "inviting_feuser", "dummy__owning_group"
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
        "group": invite.dummy.owning_group,
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
# Group management
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def create_group(request):
    name = request.POST.get("name", "").strip()
    if not name:
        return redirect("buddies:my_buddies")
    group = BuddyGroupService.create_group(request.feuser, name)
    return redirect("buddies:group_detail", group_id=group.uid)


@feuser_required
def group_detail(request, group_id):
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(
        BuddyGroup.objects.prefetch_related(
            "members__feuser", "members__dummy"
        ),
        uid=group_id,
        members__feuser=feuser,
    )
    is_admin = group.admin_feuser_id == feuser.pk
    pending_invites = BuddyQueryService.pending_group_invites_for_group(group) if is_admin else []

    feuser_members = [
        m for m in group.members.all() if m.feuser_id and m.feuser_id != feuser.pk
    ]
    dummy_members = [m for m in group.members.all() if m.dummy_id]

    breakdown = BuddyQueryService.get_group_full_breakdown(feuser, group)

    # Serialize D3 data
    breakdown_graph_json = json.dumps({
        "nodes": [
            {"key": k, "name": v["name"], "is_me": v["is_me"]}
            for k, v in breakdown["member_map"].items()
        ],
        "links": [
            {
                "from": t["from_key"],
                "from_name": t["from_name"],
                "to": t["to_key"],
                "to_name": t["to_name"],
                "amount": float(t["amount"]),
            }
            for t in breakdown["simplified"]
        ],
    })

    return render(request, "buddies/group_detail.html", {
        "active_nav": "my_buddies",
        "group": group,
        "is_admin": is_admin,
        "feuser_members": feuser_members,
        "dummy_members": dummy_members,
        "pending_invites": pending_invites,
        "breakdown": breakdown,
        "breakdown_graph_json": breakdown_graph_json,
        "currency": feuser.currency,
    })


@feuser_required
@require_POST
def group_invite_member(request, group_id):
    from django.conf import settings as django_settings
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("buddies:group_detail", group_id=group_id)

    outcome, obj = BuddyGroupService.invite_member(group, feuser, email)
    if outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "self":
        django_messages.error(request, "You cannot invite yourself.")
    elif outcome == "already_member":
        django_messages.info(request, f"{email} is already a member of this group.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated. Share this registration link: {site_url}/register/")
    elif outcome == "onboarding":
        django_messages.success(request, f"A registration and group invitation has been sent to {email}.")
    elif outcome == "invite":
        django_messages.success(request, f"Group invitation sent to {email}.")
    elif outcome == "member":
        django_messages.success(request, f"{email} has been added to the group.")
    return redirect("buddies:group_detail", group_id=group_id)


@feuser_required
@require_POST
def group_revoke_invite(request, group_id, token):
    from .models import BuddyGroup
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=request.feuser)
    BuddyGroupService.revoke_group_invite(token, request.feuser)
    return redirect("buddies:group_detail", group_id=group_id)


@feuser_required
@require_POST
def group_remove_member(request, group_id, member_id):
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    member = get_object_or_404(BuddyGroupMember, uid=member_id, group=group)

    if member.feuser_id == feuser.pk:
        django_messages.error(request, "You cannot remove yourself. Transfer admin rights first or dissolve the group.")
        return redirect("buddies:group_detail", group_id=group_id)

    if member.dummy_id:
        BuddyGroupService.delete_group_dummy(group, feuser, member.dummy)
    else:
        BuddyGroupService.remove_member(group, feuser, member)

    return redirect("buddies:group_detail", group_id=group_id)


@feuser_required
@require_POST
def group_add_dummy(request, group_id):
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    name = request.POST.get("display_name", "").strip()
    if name:
        BuddyGroupService.create_group_dummy(group, feuser, name)
    return redirect("buddies:group_detail", group_id=group_id)


@feuser_required
@require_POST
def group_send_merge(request, group_id, dummy_id):
    from django.conf import settings as django_settings
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_group=group)
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("buddies:group_detail", group_id=group_id)
    outcome, obj = BuddyGroupService.send_group_dummy_merge_invite(group, feuser, dummy, email)
    if outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated. Share this link: {site_url}/register/")
    elif outcome in ("onboarding", "invite"):
        django_messages.success(request, f"Merge invitation sent to {email}.")
    return redirect("buddies:group_detail", group_id=group_id)


@feuser_required
@require_POST
def group_transfer_admin(request, group_id):
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    try:
        new_admin_id = int(request.POST.get("new_admin_id", 0))
        new_admin = FeUser.objects.get(pk=new_admin_id, is_active=True)
    except (ValueError, FeUser.DoesNotExist):
        django_messages.error(request, "Invalid user selection.")
        return redirect("buddies:group_detail", group_id=group_id)
    ok = BuddyGroupService.transfer_admin(group, feuser, new_admin)
    if not ok:
        django_messages.error(request, "That user is not a group member.")
    return redirect("buddies:group_detail", group_id=group_id)


@feuser_required
@require_POST
def group_leave(request, group_id):
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(
        BuddyGroup.objects.prefetch_related("members"),
        uid=group_id,
        members__feuser=feuser,
    )
    if group.admin_feuser_id == feuser.pk:
        django_messages.error(request, "You are the group admin. Transfer admin rights to another member before leaving.")
        return redirect("buddies:group_detail", group_id=group_id)
    try:
        member = BuddyGroupMember.objects.get(group=group, feuser=feuser)
    except BuddyGroupMember.DoesNotExist:
        return redirect("buddies:my_buddies")
    BuddyGroupService.remove_member(group, group.admin_feuser, member)
    django_messages.success(request, f'You have left the group "{group.name}".')
    return redirect("buddies:my_buddies")


@feuser_required
@require_POST
def group_dissolve(request, group_id):
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    confirmed = request.POST.get("confirmed") == "yes"
    if not confirmed:
        return render(request, "buddies/group_dissolve_confirm.html", {
            "active_nav": "my_buddies",
            "group": group,
        })
    BuddyGroupService.dissolve_group(group, feuser)
    django_messages.success(request, f'Group "{group.name}" has been dissolved.')
    return redirect("buddies:my_buddies")


# ---------------------------------------------------------------------------
# Group invite accept/decline
# ---------------------------------------------------------------------------

@feuser_required
def view_group_invite(request, token):
    try:
        invite = BuddyGroupInvite.objects.select_related(
            "group", "inviting_feuser"
        ).get(token=token)
    except BuddyGroupInvite.DoesNotExist:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if not invite.is_valid():
        invite.delete()
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if request.feuser.email.lower() != invite.invitee_email.lower():
        return render(request, "buddies/invite_wrong_account.html", {
            "active_nav": "buddies",
            "invite": invite,
        })

    return render(request, "buddies/group_invite_view.html", {
        "active_nav": "buddies",
        "invite": invite,
        "inviter_name": _display_name(invite.inviting_feuser),
    })


@feuser_required
@require_POST
def accept_group_invite(request, token):
    group = BuddyGroupService.accept_group_invite(token, request.feuser)
    if group is None:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})
    django_messages.success(request, f'You joined the group "{group.name}".')
    return redirect("buddies:group_detail", group_id=group.uid)


@feuser_required
@require_POST
def decline_group_invite(request, token):
    BuddyGroupService.decline_group_invite(token, request.feuser)
    return redirect("buddies:my_buddies")


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
