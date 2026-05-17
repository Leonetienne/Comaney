import json
from decimal import Decimal

from django.shortcuts import redirect, render

from budget.decorators import feuser_required
from ..services import BuddyQueryService


def _debts_to_json(unified_debts) -> str:
    rows = []
    for info in unified_debts:
        rows.append({"name": info["display_name"], "net": float(info["net"])})
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

    # Expenses where feuser must confirm they paid (owning_feuser, buddy_approved=False).
    # Settlement expenses (settled=True) are excluded: the debtor must never see Approve/Reject
    # controls for their own settlement record.
    pending_as_expense_owner = (
        Expense.objects
        .filter(owning_feuser=feuser, buddy_approved=False, settled=False)
        .select_related("upfront_payee_dummy", "buddy_group")
        .order_by("-date_created")
    )

    # Settlements where feuser is the creditor and must confirm receipt.
    pending_as_creditor = (
        Expense.objects
        .filter(buddy_spendings__participant_feuser=feuser, buddy_approved=False)
        .select_related("owning_feuser", "upfront_payee_dummy", "buddy_group")
        .distinct()
        .order_by("-date_created")
    )

    admin_group_ids = list(BuddyGroup.objects.filter(admin_feuser=feuser).values_list("uid", flat=True))

    pending_dummy_expense_owners = []
    pending_dummy_creditor_settlements = []

    if admin_group_ids:
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
        "feuser_key": feuser_key,
        "direct_settle_members_json": json.dumps(direct_settle_members),
        "settle_debts_json": json.dumps(settle_debts),
        "pending_as_expense_owner": pending_as_expense_owner,
        "pending_as_creditor": pending_as_creditor,
        "pending_dummy_expense_owners": pending_dummy_expense_owners,
        "pending_dummy_creditor_settlements": pending_dummy_creditor_settlements,
    })
