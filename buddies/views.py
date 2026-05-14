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
    BuddySettlementService,
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
    from decimal import Decimal
    from budget.models import Expense
    feuser = request.feuser
    unified_debts = BuddyQueryService.get_all_debts_unified(feuser)
    all_shared = BuddyQueryService.shared_expenses(feuser)
    direct_expenses = all_shared.filter(buddy_group__isnull=True)
    my_groups_summary = BuddyQueryService.get_group_summaries_for_feuser(feuser)

    settle_candidates = [
        {
            "key": f"f{info['feuser'].pk}" if info["type"] == "feuser" else f"d{info['dummy'].pk}",
            "name": info["display_name"],
            "amount": -info["net"],
            "is_real_user": info["type"] == "feuser",
        }
        for info in unified_debts
        if info["net"] < Decimal("-0.005")
    ]

    # Section 1: expenses where feuser must confirm they paid (owning_feuser, buddy_approved=False).
    # Settlement expenses (settled=True) are explicitly excluded: the debtor created those
    # themselves and must never be shown Approve/Reject controls for their own settlement.
    pending_as_expense_owner = (
        Expense.objects
        .filter(owning_feuser=feuser, buddy_approved=False, settled=False)
        .select_related("upfront_payee_dummy", "buddy_group")
        .order_by("-date_created")
    )

    # Section 2: settlements where feuser is the creditor and must confirm receipt
    pending_as_creditor = (
        Expense.objects
        .filter(buddy_spendings__participant_feuser=feuser, buddy_approved=False)
        .select_related("owning_feuser", "upfront_payee_dummy", "buddy_group")
        .distinct()
        .order_by("-date_created")
    )

    # Sections 3 and 4: admin-only, for dummy members of groups the feuser admins
    from .models import BuddyGroup
    admin_group_ids = list(BuddyGroup.objects.filter(admin_feuser=feuser).values_list("uid", flat=True))

    pending_dummy_expense_owners = []
    pending_dummy_creditor_settlements = []

    if admin_group_ids:
        # Section 3: expenses where a group dummy is the upfront payer and needs admin confirmation
        dummy_expense_qs = (
            Expense.objects
            .filter(
                buddy_group_id__in=admin_group_ids,
                is_dummy=True,
                buddy_approved=False,
            )
            .select_related("owning_feuser", "upfront_payee_dummy", "buddy_group")
            .order_by("-date_created")
        )
        pending_dummy_expense_owners = list(dummy_expense_qs)

        # Section 4: settlements where a group dummy is the creditor and needs admin confirmation
        dummy_cred_qs = (
            Expense.objects
            .filter(
                buddy_spendings__participant_dummy__owning_group_id__in=admin_group_ids,
                buddy_approved=False,
            )
            .select_related("owning_feuser", "upfront_payee_dummy", "buddy_group")
            .prefetch_related("buddy_spendings__participant_dummy")
            .distinct()
            .order_by("-date_created")
        )
        admin_group_id_set = set(admin_group_ids)
        for exp in dummy_cred_qs:
            for bs in exp.buddy_spendings.all():
                if bs.participant_dummy_id and bs.participant_dummy.owning_group_id in admin_group_id_set:
                    pending_dummy_creditor_settlements.append({
                        "expense": exp,
                        "dummy": bs.participant_dummy,
                    })
                    break

    return render(request, "buddies/buddy_summary.html", {
        "active_nav": "buddy_summary",
        "direct_expenses": direct_expenses,
        "my_groups_summary": my_groups_summary,
        "debts_json": _debts_to_json(unified_debts),
        "settle_candidates": settle_candidates,
        "pending_as_expense_owner": pending_as_expense_owner,
        "pending_as_creditor": pending_as_creditor,
        "pending_dummy_expense_owners": pending_dummy_expense_owners,
        "pending_dummy_creditor_settlements": pending_dummy_creditor_settlements,
    })


@feuser_required
@require_POST
def settle_direct(request):
    selected = request.POST.getlist("settle")
    if selected:
        count = BuddySettlementService.create_direct_settlements(request.feuser, selected)
        if count:
            django_messages.success(request, f"{count} settlement record{'s' if count != 1 else ''} created.")
    return redirect("buddies:buddy_summary")


@feuser_required
@require_POST
def settle_direct_individual(request, buddy_key):
    try:
        amount = Decimal(request.POST.get("amount", "0").replace(",", "."))
    except Exception:
        django_messages.error(request, "Invalid amount.")
        return redirect("buddies:buddy_summary")

    if amount < Decimal("0.01"):
        django_messages.error(request, "Amount must be at least 0.01.")
        return redirect("buddies:buddy_summary")

    ok = BuddySettlementService.create_direct_individual_settlement(request.feuser, buddy_key, amount)
    if ok:
        django_messages.success(request, "Settlement recorded. You still need to send the money yourself.")
    else:
        django_messages.error(request, "Settlement could not be created.")
    return redirect("buddies:buddy_summary")


@feuser_required
@require_POST
def group_settle_individual(request, group_id):
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, members__feuser=feuser)
    is_admin = group.admin_feuser_id == feuser.pk

    debtor_key = request.POST.get("debtor_key", "").strip()
    creditor_key = request.POST.get("creditor_key", "").strip()
    try:
        amount = Decimal(request.POST.get("amount", "0").replace(",", "."))
    except Exception:
        django_messages.error(request, "Invalid amount.")
        return redirect("buddies:group_detail", group_id=group_id)

    if amount < Decimal("0.01"):
        django_messages.error(request, "Amount must be at least 0.01.")
        return redirect("buddies:group_detail", group_id=group_id)

    feuser_key = f"f{feuser.pk}"
    if not is_admin:
        debtor_key = feuser_key

    member_keys = set()
    for m in group.members.all():
        if m.feuser_id:
            member_keys.add(f"f{m.feuser_id}")
        if m.dummy_id:
            member_keys.add(f"d{m.dummy_id}")

    if debtor_key not in member_keys or creditor_key not in member_keys:
        django_messages.error(request, "Invalid member selection.")
        return redirect("buddies:group_detail", group_id=group_id)

    if debtor_key == creditor_key:
        django_messages.error(request, "Debtor and creditor must be different.")
        return redirect("buddies:group_detail", group_id=group_id)

    ok = BuddySettlementService.create_individual_group_settlement(
        feuser, group, debtor_key, creditor_key, amount
    )
    if ok:
        django_messages.success(request, "Settlement record created. The creditor will be asked to confirm receipt.")
    else:
        django_messages.error(request, "Settlement could not be created. Check the selected members and amount.")
    return redirect("buddies:group_detail", group_id=group_id)


@feuser_required
@require_POST
def group_settle_all(request, group_id):
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    result = BuddySettlementService.create_group_wide_settlements(feuser, group)
    count = result["created"]
    if count:
        django_messages.success(request, f"{count} settlement record{'s' if count != 1 else ''} created. Emails have been sent to all members.")
    else:
        django_messages.info(request, "No outstanding debts to settle.")
    return redirect("buddies:group_detail", group_id=group_id)


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

    feuser_key = f"f{feuser.pk}"
    dummy_pks_in_group = {m.dummy_id for m in group.members.all() if m.dummy_id}

    # Annotate each expense with approval needs and delete/unlink permissions
    for exp_data in breakdown["expenses"]:
        exp = exp_data["expense"]
        exp_data["creditor_approval_needed"] = False

        if not exp.buddy_approved:
            for share in exp_data["participant_shares"]:
                if share["key"] == feuser_key:
                    exp_data["creditor_approval_needed"] = True
                    break

        is_feuser_direct_owner = exp.owning_feuser_id == feuser.pk and not exp.is_dummy
        is_dummy_exp_in_group = (
            exp.is_dummy
            and exp.upfront_payee_dummy_id
            and exp.upfront_payee_dummy_id in dummy_pks_in_group
        )
        exp_data["can_delete"] = is_feuser_direct_owner or (is_admin and is_dummy_exp_in_group)
        exp_data["can_unlink"] = is_feuser_direct_owner or is_admin

    # Raw D3 graph: aggregate approved payer->participant flows per pair, then net opposing pairs
    raw_flows: dict = {}
    for exp_data in breakdown["expenses"]:
        if not exp_data["expense"].buddy_approved:
            continue
        pk = exp_data["payer_key"]
        for share in exp_data["participant_shares"]:
            edge = (share["key"], pk)
            raw_flows[edge] = raw_flows.get(edge, Decimal("0")) + share["amount"]

    netted_flows: dict = {}
    for (frm, to), amount in raw_flows.items():
        if (to, frm) in netted_flows:
            opposite = netted_flows[(to, frm)]
            if amount > opposite:
                del netted_flows[(to, frm)]
                netted_flows[(frm, to)] = amount - opposite
            elif amount < opposite:
                netted_flows[(to, frm)] = opposite - amount
            # equal: both cancel, neither entry added
        else:
            netted_flows[(frm, to)] = amount
    raw_flows = netted_flows

    graph_nodes = [
        {"key": k, "name": v["name"], "is_me": v["is_me"]}
        for k, v in breakdown["member_map"].items()
    ]

    raw_graph_json = json.dumps({
        "nodes": graph_nodes,
        "links": [
            {"from": f, "to": t, "amount": float(a)}
            for (f, t), a in raw_flows.items()
            if a > Decimal("0.005")
        ],
    })

    simplified_graph_json = json.dumps({
        "nodes": graph_nodes,
        "links": [
            {
                "from": t["from_key"],
                "to": t["to_key"],
                "amount": float(t["amount"]),
            }
            for t in breakdown["simplified"]
        ],
    })

    # Raw pairwise netted debt amounts for JS pre-fill in the settle form
    raw_debts_json = json.dumps([
        {"from": frm, "to": to, "amount": float(amount)}
        for (frm, to), amount in raw_flows.items()
        if amount > Decimal("0.005")
    ])

    # My-perspective summary from the simplified model
    my_balances = []
    for t in breakdown["simplified"]:
        if t["from_is_me"]:
            my_balances.append({"name": t["to_name"], "you_owe": True, "amount": t["amount"]})
        elif t["to_is_me"]:
            my_balances.append({"name": t["from_name"], "you_owe": False, "amount": t["amount"]})
    my_balances.sort(key=lambda x: -x["amount"])

    # All members serialised for settle form dropdowns
    all_members_json = json.dumps([
        {"key": feuser_key, "name": "You", "is_me": True},
        *[
            {
                "key": f"f{m.feuser.pk}",
                "name": f"{m.feuser.first_name} {m.feuser.last_name}".strip() or m.feuser.email,
                "is_me": False,
            }
            for m in feuser_members
        ],
        *[
            {"key": f"d{m.dummy.pk}", "name": m.dummy.display_name, "is_me": False, "is_dummy": True}
            for m in dummy_members
        ],
    ])

    # Admin settle-all summary for confirmation dialog
    settle_all_pairs_json = json.dumps([
        {
            "from": t["from_name"],
            "to": t["to_name"],
            "amount": float(t["amount"]),
        }
        for t in breakdown["simplified"]
    ])

    pending_expenses = [e for e in breakdown["expenses"] if not e["expense"].buddy_approved]
    approved_expenses = [e for e in breakdown["expenses"] if e["expense"].buddy_approved]

    return render(request, "buddies/group_detail.html", {
        "active_nav": "my_buddies",
        "group": group,
        "is_admin": is_admin,
        "feuser_key": feuser_key,
        "feuser_members": feuser_members,
        "dummy_members": dummy_members,
        "pending_invites": pending_invites,
        "breakdown": breakdown,
        "pending_expenses": pending_expenses,
        "approved_expenses": approved_expenses,
        "my_balances": my_balances,
        "raw_graph_json": raw_graph_json,
        "simplified_graph_json": simplified_graph_json,
        "raw_debts_json": raw_debts_json,
        "all_members_json": all_members_json,
        "settle_all_pairs_json": settle_all_pairs_json,
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


@feuser_required
def approve_settlement_as_creditor(request, expense_id):
    """
    Creditor-side settlement approval. GET shows a confirmation page;
    POST confirms receipt. The email link points here (GET).
    """
    from budget.models import Expense
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
            debtor_label = expense.upfront_payee_dummy.display_name
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
        django_messages.success(request, "Settlement confirmed. Thank you!")
        if expense.buddy_group_id:
            return redirect("buddies:group_detail", group_id=expense.buddy_group_id)
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
    from budget.models import Expense
    expense = get_object_or_404(
        Expense,
        uid=expense_id,
        buddy_approved=False,
        is_buddies_settlement=True,
        buddy_spendings__participant_feuser=request.feuser,
    )
    debtor = expense.owning_feuser
    creditor = request.feuser
    group_id = expense.buddy_group_id
    BuddyEmailService.send_settlement_rejection_notification(expense, creditor, debtor)
    expense.delete()
    django_messages.warning(request, "Settlement rejected. The debtor has been notified.")
    if group_id:
        return redirect("buddies:group_detail", group_id=group_id)
    return redirect("buddies:buddy_summary")


@feuser_required
@require_POST
def admin_approve_dummy_settlement(request, group_id, expense_id):
    """Admin confirms on behalf of a dummy upfront-payer or dummy creditor in their group."""
    from budget.models import Expense
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    expense = get_object_or_404(
        Expense,
        uid=expense_id,
        buddy_group=group,
        buddy_approved=False,
    )
    has_dummy_upfront = expense.is_dummy and expense.upfront_payee_dummy_id
    has_dummy_creditor = expense.buddy_spendings.filter(
        participant_dummy__owning_group=group
    ).exists()
    if not (has_dummy_upfront or has_dummy_creditor):
        django_messages.error(request, "This expense does not involve an offline member of this group.")
        return redirect("buddies:buddy_summary")
    BuddyLifecycleService.approve_expense(expense)
    django_messages.success(request, "Approved on behalf of the offline member.")
    return redirect("buddies:buddy_summary")


@feuser_required
@require_POST
def group_expense_delete(request, group_id, expense_id):
    from budget.models import Expense
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, members__feuser=feuser)
    is_admin = group.admin_feuser_id == feuser.pk
    dummy_pks_in_group = {
        m.dummy_id for m in group.members.all() if m.dummy_id
    }

    try:
        expense = Expense.objects.get(uid=expense_id, buddy_group=group)
    except Expense.DoesNotExist:
        django_messages.error(request, "Expense not found.")
        return redirect("buddies:group_detail", group_id=group_id)

    is_feuser_direct_owner = expense.owning_feuser_id == feuser.pk and not expense.is_dummy
    is_dummy_exp_in_group = (
        expense.is_dummy
        and expense.upfront_payee_dummy_id
        and expense.upfront_payee_dummy_id in dummy_pks_in_group
    )

    if not (is_feuser_direct_owner or (is_admin and is_dummy_exp_in_group)):
        django_messages.error(request, "You do not have permission to delete this expense.")
        return redirect("buddies:group_detail", group_id=group_id)

    expense.delete()
    django_messages.success(request, "Expense deleted.")
    return redirect("buddies:group_detail", group_id=group_id)


@feuser_required
@require_POST
def group_expense_unlink(request, group_id, expense_id):
    from budget.models import Expense
    from .models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, members__feuser=feuser)
    is_admin = group.admin_feuser_id == feuser.pk

    try:
        expense = Expense.objects.get(uid=expense_id, buddy_group=group)
    except Expense.DoesNotExist:
        django_messages.error(request, "Expense not found.")
        return redirect("buddies:group_detail", group_id=group_id)

    is_feuser_direct_owner = expense.owning_feuser_id == feuser.pk and not expense.is_dummy
    if not (is_feuser_direct_owner or is_admin):
        django_messages.error(request, "You do not have permission to unlink this expense.")
        return redirect("buddies:group_detail", group_id=group_id)

    # Collect people to notify before wiping the spendings rows
    notify_feusers = set()
    if is_admin and not is_feuser_direct_owner:
        if not expense.is_dummy:
            notify_feusers.add(expense.owning_feuser)
        for bs in expense.buddy_spendings.select_related("participant_feuser").all():
            if bs.participant_feuser_id and bs.participant_feuser_id != feuser.pk:
                notify_feusers.add(bs.participant_feuser)

    expense.buddy_spendings.all().delete()
    expense.buddy_group = None
    expense.is_dummy = False
    expense.upfront_payee_dummy = None
    expense.buddy_approved = True
    expense.save()

    if notify_feusers:
        from .services import BuddyEmailService
        for fu in notify_feusers:
            BuddyEmailService.send_expense_unlinked_notification(
                expense=expense,
                admin_feuser=feuser,
                group=group,
                notify_feuser=fu,
                is_owner=(fu.pk == expense.owning_feuser_id),
            )

    django_messages.success(request, "Expense unlinked from the group. It remains in the owner's expense list.")
    return redirect("buddies:group_detail", group_id=group_id)
