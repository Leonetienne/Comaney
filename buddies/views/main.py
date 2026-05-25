import io
import json
import zipfile
from datetime import date
from decimal import Decimal

from comaney.json_utils import safe_json

from django.http import HttpResponse
from django.shortcuts import redirect, render

from budget.decorators import feuser_required
from budget.query_parser import apply_query
from budget.views._period import _date_range_presets_context, resolve_date_range
from ..services import BuddyExportService, BuddyQueryService


_SORT_FIELD_MAP = {
    "date":  lambda ed: (ed["expense"].date_due or date.min),
    "title": lambda ed: ed["expense"].title.lower(),
    "value": lambda ed: ed["expense"].value,
}


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
    return safe_json(rows)


@feuser_required
def buddies_page(request):
    return redirect("buddies:my_buddies")


@feuser_required
def my_buddies_page(request):
    feuser = request.feuser
    unified_debts = BuddyQueryService.get_all_debts_unified(feuser)
    pending_in = BuddyQueryService.pending_invites_incoming(feuser)
    pending_out = BuddyQueryService.pending_invites_outgoing(feuser)
    pending_onboarding_out = BuddyQueryService.pending_onboarding_invites_outgoing(feuser)
    merge_in = BuddyQueryService.pending_merge_invites_incoming(feuser)
    merge_out = BuddyQueryService.pending_merge_invites_outgoing(feuser)
    group_invites_in = BuddyQueryService.pending_group_invites_incoming(feuser)

    return render(request, "buddies/my_buddies.html", {
        "active_nav": "my_buddies",
        "unified_debts": unified_debts,
        "pending_invites_in": pending_in,
        "pending_invites_out": pending_out,
        "pending_onboarding_invites_out": pending_onboarding_out,
        "merge_invites_in": merge_in,
        "merge_invites_out": merge_out,
        "group_invites_in": group_invites_in,
    })


def _compute_direct_expenses(feuser, start_date, end_date):
    from budget.models import Expense, ExpenseDataOverlay
    all_shared = BuddyQueryService.shared_expenses(feuser)
    direct_expenses_qs = all_shared.filter(project__isnull=True).select_related(
        "owning_feuser", "upfront_payee_dummy"
    ).prefetch_related(
        "buddy_spendings__participant_feuser", "buddy_spendings__participant_dummy"
    )

    if start_date and end_date:
        direct_expenses_qs = direct_expenses_qs.filter(
            date_due__isnull=False, date_due__gte=start_date, date_due__lte=end_date
        ) | all_shared.filter(
            project__isnull=True, date_due__isnull=True,
            date_created__date__gte=start_date, date_created__date__lte=end_date,
        ).select_related("owning_feuser", "upfront_payee_dummy").prefetch_related(
            "buddy_spendings__participant_feuser", "buddy_spendings__participant_dummy"
        )

    direct_expenses = list(direct_expenses_qs)
    overlay_notes = {
        o.expense_id: o.note
        for o in ExpenseDataOverlay.objects.filter(
            expense_id__in=[e.pk for e in direct_expenses],
            feuser=feuser,
        )
    }

    direct_expense_data = []
    for exp in direct_expenses:
        if exp.is_dummy and exp.upfront_payee_dummy_id:
            payer_name = exp.upfront_payee_dummy.display_name + " (offline buddy)"
            payer_is_me = False
        else:
            fu = exp.owning_feuser
            payer_name = f"{fu.first_name} {fu.last_name}".strip() or fu.email
            payer_is_me = fu.pk == feuser.pk
        participant_shares = []
        total_pct = Decimal("0")
        for bs in exp.buddy_spendings.all():
            if bs.participant_feuser_id:
                pf = bs.participant_feuser
                name = f"{pf.first_name} {pf.last_name}".strip() or pf.email
                is_me = pf.pk == feuser.pk
            else:
                name = bs.participant_dummy.display_name + " (offline buddy)"
                is_me = False
            amount = exp.value * bs.share_percent / 100
            total_pct += bs.share_percent
            participant_shares.append({"name": name, "is_me": is_me, "amount": amount, "percent": bs.share_percent})
        payer_pct = Decimal("100") - total_pct
        raw_note = overlay_notes.get(exp.pk)
        direct_expense_data.append({
            "expense": exp,
            "payer_name": payer_name,
            "payer_is_me": payer_is_me,
            "payer_amount": exp.value * payer_pct / 100,
            "payer_percent": payer_pct,
            "participant_shares": participant_shares,
            "visible_note": raw_note if raw_note is not None else exp.note,
        })
    return direct_expense_data


@feuser_required
def direct_expense_list_partial(request):
    from budget.models import Expense
    feuser = request.feuser

    start_date = None
    end_date   = None
    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw   = request.GET.get("date_to", "").strip()
    if date_from_raw and date_to_raw:
        try:
            start_date = date.fromisoformat(date_from_raw)
            end_date   = date.fromisoformat(date_to_raw)
        except ValueError:
            pass

    q = request.GET.get("q", "").strip()
    hide_recurring = request.GET.get("hide_recurring") == "1"
    sort_by  = request.GET.get("sort_by", "date")
    sort_dir = request.GET.get("sort_dir", "desc")

    effective_q = q
    if hide_recurring:
        effective_q = (effective_q + " recurring=no").strip() if effective_q else "recurring=no"

    matching_pks = None
    if effective_q:
        base_qs = BuddyQueryService.shared_expenses(feuser).filter(project__isnull=True)
        matching_pks = set(apply_query(base_qs, effective_q, feuser=feuser).values_list("pk", flat=True))

    direct_expense_data = _compute_direct_expenses(feuser, start_date, end_date)

    if matching_pks is not None:
        direct_expense_data = [ed for ed in direct_expense_data if ed["expense"].pk in matching_pks]

    sort_key = _SORT_FIELD_MAP.get(sort_by, _SORT_FIELD_MAP["date"])
    direct_expense_data = sorted(direct_expense_data, key=sort_key, reverse=(sort_dir == "desc"))

    return render(request, "buddies/direct_expense_partial.html", {
        "direct_expense_data": direct_expense_data,
        "currency": feuser.currency,
    })


@feuser_required
def buddy_summary_page(request):
    from budget.models import Expense
    from ..models import Project

    feuser = request.feuser
    unified_debts = BuddyQueryService.get_all_debts_unified(feuser)

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

    admin_group_ids = list(Project.objects.filter(admin_feuser=feuser).values_list("uid", flat=True))
    admin_group_id_set = set(admin_group_ids)

    pending_approvals = []

    # Expenses logged on feuser's behalf (personal buddy only, not project).
    # Settlement records and project expenses are excluded: the former must not be
    # self-approved; the latter are confirmed on the project detail page.
    for exp in (
        Expense.objects
        .filter(owning_feuser=feuser, buddy_approved=False, is_buddies_settlement=False, project__isnull=True)
        .select_related("project")
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
        .select_related("owning_feuser", "upfront_payee_dummy", "project")
        .distinct()
        .order_by("-date_created")
    ):
        pending_approvals.append({"expense": exp, "kind": "feuser_creditor", "dummy": None})

    if admin_group_ids:
        # Non-settlement expenses where a group dummy paid upfront (admin confirms).
        for exp in (
            Expense.objects
            .filter(
                project_id__in=admin_group_ids,
                is_dummy=True,
                is_buddies_settlement=False,
                buddy_approved=False,
            )
            .select_related("upfront_payee_dummy", "project")
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
                is_buddies_settlement=True,
            )
            .select_related("owning_feuser", "upfront_payee_dummy", "project")
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


    me_avatar_json = safe_json({
        "has_pic": feuser.profile_picture,
        "avatar_url": feuser.ppic_url if feuser.profile_picture else None,
        "initials": feuser.initials,
    })

    ctx = {
        "active_nav": "buddy_summary",
        "currency": feuser.currency,
        "debts_json": _debts_to_json(unified_debts),
        "me_avatar_json": me_avatar_json,
        "feuser_key": feuser_key,
        "direct_settle_members_json": safe_json(direct_settle_members),
        "settle_debts_json": safe_json(settle_debts),
        "pending_approvals": pending_approvals,
        "initial_date_from": request.GET.get("date_from", ""),
        "initial_date_to":   request.GET.get("date_to", ""),
    }
    ctx.update(_date_range_presets_context(feuser))
    return render(request, "buddies/buddy_summary.html", ctx)


@feuser_required
def buddy_summary_export(request):
    """Download direct-buddies.csv (the combined real-user + offline buddy
    roster, never date-filtered), direct-buddy-expenses.csv, and
    direct-buddy-expense-participation.csv (both scoped to the currently
    selected date range) as a ZIP, mirroring the per-project export."""
    feuser = request.feuser
    start_date, end_date = resolve_date_range(request, feuser)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        BuddyExportService.write_buddy_csvs(zf, feuser, start_date=start_date, end_date=end_date)

    filename = f"direct_buddies_export_{start_date.isoformat()}_to_{end_date.isoformat()}.zip"
    response = HttpResponse(buf.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
