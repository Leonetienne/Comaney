from decimal import Decimal

from django.contrib import messages as django_messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from ..services import BuddySettlementService


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
def settle_direct_freeform(request):
    """Single-form personal settlement: debtor_key and creditor_key come from POST body."""
    feuser = request.feuser
    feuser_key = f"f{feuser.pk}"
    debtor_key = request.POST.get("debtor_key", feuser_key).strip() or feuser_key
    creditor_key = request.POST.get("creditor_key", "").strip()
    try:
        amount = Decimal(request.POST.get("amount", "0").replace(",", "."))
    except Exception:
        django_messages.error(request, "Invalid amount.")
        return redirect("buddies:buddy_summary")

    if amount < Decimal("0.01"):
        django_messages.error(request, "Amount must be at least 0.01.")
        return redirect("buddies:buddy_summary")

    if debtor_key == feuser_key:
        ok = BuddySettlementService.create_direct_individual_settlement(feuser, creditor_key, amount)
        if ok:
            django_messages.success(request, "Settlement recorded. You still need to send the money yourself.")
        else:
            django_messages.error(request, "Settlement could not be created.")
    else:
        ok = BuddySettlementService.create_direct_dummy_settlement(feuser, debtor_key, amount)
        if ok:
            django_messages.success(request, "Settlement recorded.")
        else:
            django_messages.error(request, "Settlement could not be created.")
    return redirect("buddies:buddy_summary")


@feuser_required
@require_POST
def group_settle_individual(request, group_id):
    from ..models import BuddyGroup
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
        creditor_is_dummy = creditor_key.startswith("d")
        debtor_is_dummy = debtor_key.startswith("d")
        both_dummies = debtor_is_dummy and creditor_is_dummy
        admin_is_debtor_paying_dummy = (
            not debtor_is_dummy
            and debtor_key == feuser_key
            and is_admin
            and creditor_is_dummy
        )
        auto_approve = both_dummies or admin_is_debtor_paying_dummy
        if auto_approve:
            msg = "Settlement record created."
        elif creditor_is_dummy:
            msg = "Settlement record created. The group admin will be asked to confirm receipt."
        else:
            msg = "Settlement record created. The creditor will be asked to confirm receipt."
        django_messages.success(request, msg)
    else:
        django_messages.error(request, "Settlement could not be created. Check the selected members and amount.")
    return redirect("buddies:group_detail", group_id=group_id)


@feuser_required
@require_POST
def group_settle_all(request, group_id):
    from ..models import BuddyGroup
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    result = BuddySettlementService.create_group_wide_settlements(feuser, group)
    count = result["created"]
    if count:
        django_messages.success(request, f"{count} settlement record{'s' if count != 1 else ''} created. Emails have been sent to all members.")
    else:
        django_messages.info(request, "No outstanding debts to settle.")
    return redirect("buddies:group_detail", group_id=group_id)
