import json
from decimal import Decimal

from django.shortcuts import redirect, render

from budget.decorators import feuser_required
from ..services import BuddyQueryService


def _debts_to_json(unified_debts) -> str:
    rows = []
    for info in unified_debts:
        obj = info["feuser"] or info["dummy"]
        has_pic = bool(obj and obj.profile_picture)
        rows.append({
            "name": info["display_name"],
            "net": float(info["net"]),
            "has_pic": has_pic,
            "avatar_url": obj.ppic_url if has_pic else None,
            "initials": obj.initials if obj else "?",
        })
    return json.dumps(rows)


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


@feuser_required
def buddy_summary_page(request):
    from budget.models import Expense
    from ..models import BuddyGroup

    feuser = request.feuser
    unified_debts = BuddyQueryService.get_all_debts_unified(feuser)
    all_shared = BuddyQueryService.shared_expenses(feuser)
    direct_expenses = all_shared.filter(buddy_group__isnull=True)
    my_groups_summary = BuddyQueryService.get_group_summaries_for_feuser(feuser)

    feuser_key = f"f{feuser.pk}"
    direct_settle_members = []
    settle_debts: dict = {}  # {debtor_key: {creditor_key: amount}}
    for _info in unified_debts:
        _key = f"f{_info['feuser'].pk}" if _info["type"] == "feuser" else f"d{_info['dummy'].pk}"
        _is_dummy = _info["type"] == "dummy"
        _net = _info["net"]
        if _net < Decimal("-0.005"):
            # feuser owes this buddy
            settle_debts.setdefault(feuser_key, {})[_key] = float(-_net)
        elif _net > Decimal("0.005"):
            # this buddy owes feuser
            settle_debts.setdefault(_key, {})[feuser_key] = float(_net)
        direct_settle_members.append({
            "key": _key,
            "name": _info["display_name"],
            "is_dummy": _is_dummy,
        })

    admin_group_ids = list(BuddyGroup.objects.filter(admin_feuser=feuser).values_list("uid", flat=True))
    admin_group_id_set = set(admin_group_ids)

    pending_approvals = []

    # Expenses logged on feuser's behalf where feuser must confirm they paid.
    # Settlements (settled=True) are excluded: the debtor must never self-approve.
    for exp in (
        Expense.objects
        .filter(owning_feuser=feuser, buddy_approved=False, settled=False)
        .select_related("buddy_group")
        .order_by("-date_created")
    ):
        pending_approvals.append({"expense": exp, "kind": "expense_owner", "dummy": None})

    # Settlements where feuser is the direct feuser creditor.
    for exp in (
        Expense.objects
        .filter(
            buddy_spendings__participant_feuser=feuser,
            buddy_approved=False,
            is_buddies_settlement=True,
        )
        .select_related("owning_feuser", "upfront_payee_dummy", "buddy_group")
        .distinct()
        .order_by("-date_created")
    ):
        pending_approvals.append({"expense": exp, "kind": "feuser_creditor", "dummy": None})

    if admin_group_ids:
        # Non-settlement expenses where a group dummy paid upfront (admin confirms).
        for exp in (
            Expense.objects
            .filter(
                buddy_group_id__in=admin_group_ids,
                is_dummy=True,
                is_buddies_settlement=False,
                buddy_approved=False,
            )
            .select_related("upfront_payee_dummy", "buddy_group")
            .order_by("-date_created")
        ):
            pending_approvals.append({"expense": exp, "kind": "dummy_payer", "dummy": exp.upfront_payee_dummy})

        # Settlements where a group dummy is the creditor (admin confirms dummy received payment).
        seen_dummy_cred = set()
        for exp in (
            Expense.objects
            .filter(
                buddy_spendings__participant_dummy__owning_group_id__in=admin_group_ids,
                buddy_approved=False,
            )
            .select_related("owning_feuser", "upfront_payee_dummy", "buddy_group")
            .prefetch_related("buddy_spendings__participant_dummy")
            .distinct()
            .order_by("-date_created")
        ):
            if exp.pk in seen_dummy_cred:
                continue
            for bs in exp.buddy_spendings.all():
                if bs.participant_dummy_id and bs.participant_dummy.owning_group_id in admin_group_id_set:
                    pending_approvals.append({"expense": exp, "kind": "dummy_creditor", "dummy": bs.participant_dummy})
                    seen_dummy_cred.add(exp.pk)
                    break

    me_avatar_json = json.dumps({
        "has_pic": feuser.profile_picture,
        "avatar_url": feuser.ppic_url if feuser.profile_picture else None,
        "initials": feuser.initials,
    })

    return render(request, "buddies/buddy_summary.html", {
        "active_nav": "buddy_summary",
        "direct_expenses": direct_expenses,
        "my_groups_summary": my_groups_summary,
        "debts_json": _debts_to_json(unified_debts),
        "me_avatar_json": me_avatar_json,
        "feuser_key": feuser_key,
        "direct_settle_members_json": json.dumps(direct_settle_members),
        "settle_debts_json": json.dumps(settle_debts),
        "pending_approvals": pending_approvals,
    })
