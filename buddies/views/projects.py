import io
import json
import re
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from comaney.json_utils import safe_json

from django.conf import settings
from django.contrib import messages as django_messages
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from budget.models import Expense
from budget.query_parser import apply_query, has_date_filter
from budget.views._period import _date_range_presets_context, resolve_date_range
from feusers.models import FeUser
from ..models import Project, ProjectInvite, ProjectMember, BuddySpending, DummyUser
from ..services import BuddyArchiveService, ProjectService, ProjectExportService, BuddyQueryService, _display_name


def _fetch_overlay_notes(feuser, breakdown):
    """Fetch ExpenseDataOverlay notes for all expenses in breakdown. Returns {expense_pk: note}."""
    from budget.models import ExpenseDataOverlay
    pks = [ed["expense"].pk for ed in breakdown["expenses"]]
    overlays = (
        ExpenseDataOverlay.objects
        .filter(expense_id__in=pks, feuser=feuser)
        .prefetch_related("tags")
    )
    notes = {}
    tags = {}
    for o in overlays:
        notes[o.expense_id] = o.note
        tags[o.expense_id] = [t.title for t in o.tags.all()]
    return notes, tags


def _annotate_expense_permissions(feuser, project, breakdown, is_admin, overlay_notes):
    """
    Annotate each expense_data dict in breakdown["expenses"] with permission flags
    and visible_note. Modifies dicts in-place.
    """
    feuser_key = f"f{feuser.pk}"
    dummy_pks_in_project = {m.dummy_id for m in project.members.all() if m.dummy_id}

    for exp_data in breakdown["expenses"]:
        exp = exp_data["expense"]
        exp_data["creditor_approval_needed"] = False
        exp_data["admin_approval_needed"] = False
        exp_data["owner_approval_needed"] = False

        if not exp.buddy_approved:
            if not exp.is_dummy and not exp.is_buddies_settlement and exp.owning_feuser_id == feuser.pk:
                exp_data["owner_approval_needed"] = True
            elif exp.is_buddies_settlement:
                for share in exp_data["participant_shares"]:
                    if share["key"] == feuser_key:
                        exp_data["creditor_approval_needed"] = True
                        break
            if is_admin and not exp_data["creditor_approval_needed"]:
                if exp.is_dummy and exp.upfront_payee_dummy_id and not exp.is_buddies_settlement:
                    exp_data["admin_approval_needed"] = True
                elif exp.is_buddies_settlement:
                    has_dummy_creditor = any(
                        share["key"].startswith("d")
                        and int(share["key"][1:]) in dummy_pks_in_project
                        for share in exp_data["participant_shares"]
                    )
                    if has_dummy_creditor:
                        exp_data["admin_approval_needed"] = True

        is_feuser_direct_owner = exp.owning_feuser_id == feuser.pk and not exp.is_dummy
        is_dummy_exp_in_project = (
            exp.is_dummy
            and exp.upfront_payee_dummy_id
            and exp.upfront_payee_dummy_id in dummy_pks_in_project
        )
        is_settlement_to_project_dummy = (
            exp.is_buddies_settlement
            and is_admin
            and is_feuser_direct_owner
            and any(
                share["key"].startswith("d") and int(share["key"][1:]) in dummy_pks_in_project
                for share in exp_data["participant_shares"]
            )
        )
        no_feuser_creditor = not any(
            not share["key"].startswith("d")
            for share in exp_data["participant_shares"]
        )

        if project.archived:
            exp_data["can_delete"] = False
            exp_data["can_unlink"] = False
            exp_data["can_edit"] = False
            exp_data["can_edit_overlay"] = False
        else:
            exp_data["can_delete"] = (
                is_feuser_direct_owner
                or (is_admin and is_dummy_exp_in_project)
                or is_settlement_to_project_dummy
            )
            if exp.is_buddies_settlement and exp.buddy_approved:
                can_delete_approved = (
                    is_settlement_to_project_dummy
                    or (is_admin and is_dummy_exp_in_project and no_feuser_creditor)
                )
                if not can_delete_approved:
                    exp_data["can_delete"] = False
            exp_data["can_unlink"] = is_feuser_direct_owner or is_admin
            if exp.is_buddies_settlement:
                exp_data["can_edit"] = (
                    is_settlement_to_project_dummy
                    or (is_feuser_direct_owner and not exp.buddy_approved)
                    or (is_admin and is_dummy_exp_in_project and (not exp.buddy_approved or no_feuser_creditor))
                )
            else:
                exp_data["can_edit"] = is_feuser_direct_owner or (is_admin and is_dummy_exp_in_project)
            exp_data["can_edit_overlay"] = (
                exp_data["i_am_participant"]
                and not exp.is_buddies_settlement
                and not exp_data["can_edit"]
            )
        raw_note = overlay_notes.get(exp.pk)
        exp_data["visible_note"] = raw_note if raw_note is not None else exp.note


def _is_solo(project):
    """True if the project has exactly one feuser member and no dummy members."""
    members = list(project.members.all())
    feuser_count = sum(1 for m in members if m.feuser_id)
    dummy_count = sum(1 for m in members if m.dummy_id)
    return feuser_count == 1 and dummy_count == 0


def _project_pending_counts(feuser, project_ids: list) -> dict:
    """Return {project_id: pending_approval_count} for non-archived projects."""
    if not project_ids:
        return {}
    counts = {pid: 0 for pid in project_ids}
    # Expenses where feuser is the recorded upfront payer
    for row in Expense.objects.filter(
        project_id__in=project_ids,
        owning_feuser=feuser,
        buddy_approved=False,
        is_buddies_settlement=False,
    ).values("project_id"):
        counts[row["project_id"]] += 1
    # Settlements where feuser is the creditor
    for row in Expense.objects.filter(
        project_id__in=project_ids,
        buddy_spendings__participant_feuser=feuser,
        buddy_approved=False,
        is_buddies_settlement=True,
    ).distinct().values("project_id"):
        counts[row["project_id"]] += 1
    # Admin: dummy upfront-payer expenses
    admin_ids = set(
        Project.objects.filter(admin_feuser=feuser, uid__in=project_ids)
        .values_list("uid", flat=True)
    )
    if admin_ids:
        for row in Expense.objects.filter(
            project_id__in=admin_ids,
            is_dummy=True,
            is_buddies_settlement=False,
            buddy_approved=False,
        ).values("project_id"):
            counts[row["project_id"]] += 1
        # Admin: settlements where a project dummy is the creditor
        for row in Expense.objects.filter(
            buddy_spendings__participant_dummy__owning_group_id__in=admin_ids,
            buddy_approved=False,
            is_buddies_settlement=True,
        ).distinct().values("project_id"):
            if row["project_id"] in counts:
                counts[row["project_id"]] += 1
    # Incoming offline-member merge requests for this feuser within these projects
    from ..models import DummyMergeInvite
    for row in DummyMergeInvite.objects.filter(
        invited_feuser=feuser,
        dummy__owning_group_id__in=project_ids,
        expires_at__gt=timezone.now(),
    ).values("dummy__owning_group_id"):
        counts[row["dummy__owning_group_id"]] += 1
    return counts


@feuser_required
def projects_list(request):
    feuser = request.feuser

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        if name:
            project = ProjectService.create_group(feuser, name, description=description)
            return redirect("projects:project_detail", project_id=project.uid)
        return redirect("projects:projects_list")

    # Get projects in sort order, merged with balance/spending summary data
    my_projects = BuddyQueryService.get_projects_for_feuser(feuser)
    summaries_by_id = {
        s["group"].uid: s
        for s in BuddyQueryService.get_group_summaries_for_feuser(feuser)
    }

    non_archived_ids = [p.uid for p in my_projects if not p.archived]
    pending_counts = _project_pending_counts(feuser, non_archived_ids)

    # Attach summary data to each project for the template
    project_summaries = [
        {
            "project": p,
            "net": summaries_by_id.get(p.uid, {}).get("net", Decimal("0")),
            "net_abs": summaries_by_id.get(p.uid, {}).get("net_abs", Decimal("0")),
            "net_state": summaries_by_id.get(p.uid, {}).get("net_state", "settled"),
            "group_total_spending": summaries_by_id.get(p.uid, {}).get("group_total_spending", Decimal("0")),
            "has_multiple_members": summaries_by_id.get(p.uid, {}).get("has_multiple_members", False),
            "is_admin": p.admin_feuser_id == feuser.pk,
            "pending_count": pending_counts.get(p.uid, 0),
        }
        for p in my_projects
    ]

    incoming_invites = BuddyQueryService.pending_group_invites_incoming(feuser)

    return render(request, "buddies/projects_list.html", {
        "active_nav": "projects",
        "my_projects": my_projects,
        "project_summaries": project_summaries,
        "currency": feuser.currency,
        "incoming_project_invites": incoming_invites,
    })


# Alias so the URL name works
create_project = projects_list


@feuser_required
def project_detail(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(
        Project.objects.prefetch_related(
            "members__feuser", "members__dummy"
        ),
        uid=project_id,
        members__feuser=feuser,
    )
    is_admin = project.admin_feuser_id == feuser.pk
    pending_invites = BuddyQueryService.pending_group_invites_for_group(project) if is_admin else []

    feuser_members = [
        m for m in project.members.all() if m.feuser_id and m.feuser_id != feuser.pk
    ]
    dummy_members = [m for m in project.members.all() if m.dummy_id]

    solo = _is_solo(project)

    breakdown = BuddyQueryService.get_group_full_breakdown(feuser, project)

    feuser_key = f"f{feuser.pk}"
    overlay_notes, overlay_tags = _fetch_overlay_notes(feuser, breakdown)
    _annotate_expense_permissions(feuser, project, breakdown, is_admin, overlay_notes)

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
        if frm == to:
            continue
        if (to, frm) in netted_flows:
            opposite = netted_flows[(to, frm)]
            if amount > opposite:
                del netted_flows[(to, frm)]
                netted_flows[(frm, to)] = amount - opposite
            elif amount < opposite:
                netted_flows[(to, frm)] = opposite - amount
            else:
                del netted_flows[(to, frm)]
        else:
            netted_flows[(frm, to)] = amount
    raw_flows = netted_flows

    graph_nodes = []
    for k, v in breakdown["member_map"].items():
        obj = v.get("user_obj")
        has_pic = bool(obj and obj.profile_picture)
        graph_nodes.append({
            "key": k,
            "name": v["name"],
            "is_me": v["is_me"],
            "has_pic": has_pic,
            "avatar_url": obj.ppic_url if has_pic else None,
            "initials": obj.initials if obj else "?",
        })

    raw_graph_json = safe_json({
        "nodes": graph_nodes,
        "links": [
            {"from": f, "to": t, "amount": float(a)}
            for (f, t), a in raw_flows.items()
            if a > Decimal("0.005") and f != t
        ],
    })

    simplified_graph_json = safe_json({
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

    raw_debts_json = safe_json([
        {"from": frm, "to": to, "amount": float(amount)}
        for (frm, to), amount in raw_flows.items()
        if amount > Decimal("0.005") and frm != to
    ])

    my_balances = []
    for t in breakdown["simplified"]:
        if t["from_is_me"]:
            my_balances.append({"name": t["to_name"], "you_owe": True, "amount": t["amount"]})
        elif t["to_is_me"]:
            my_balances.append({"name": t["from_name"], "you_owe": False, "amount": t["amount"]})
    my_balances.sort(key=lambda x: -x["amount"])

    all_members_json = safe_json([
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
            {"key": f"d{m.dummy.pk}", "name": m.dummy.display_name + " (offline member)", "is_me": False, "is_dummy": True}
            for m in dummy_members
        ],
    ])

    settle_all_pairs_json = safe_json([
        {
            "from": t["from_name"],
            "to": t["to_name"],
            "amount": float(t["amount"]),
        }
        for t in breakdown["simplified"]
    ])

    pending_expenses = [e for e in breakdown["expenses"] if not e["expense"].buddy_approved]
    approved_expenses = [e for e in breakdown["expenses"] if e["expense"].buddy_approved]

    project_url = reverse("projects:project_detail", args=[project.uid])
    ctx = {
        "active_nav": "projects",
        "project": project,
        "group": project,
        "is_admin": is_admin,
        "is_solo": solo,
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
        "member_count": len(breakdown["member_map"]),
        "has_multiple_members": len(breakdown["member_map"]) > 1,
        "currency": feuser.currency,
        "project_url": project_url,
        "initial_date_from": request.GET.get("date_from", ""),
        "initial_date_to":   request.GET.get("date_to", ""),
    }
    ctx.update(_date_range_presets_context(feuser))
    return render(request, "buddies/project_detail.html", ctx)

def _compute_project_charts(feuser, project, start_date, end_date):
    """
    Compute spending pie, spending-over-time, and tag-dist for a project.
    If start_date/end_date are provided, only approved expenses in that range
    are included. Returns a dict ready for JSON serialization.
    """
    breakdown = BuddyQueryService.get_group_full_breakdown(feuser, project)
    overlay_notes, overlay_tags = _fetch_overlay_notes(feuser, breakdown)

    approved_expenses = [e for e in breakdown["expenses"] if e["expense"].buddy_approved]

    # Apply date filter to approved expenses
    if start_date and end_date:
        def _in_range(ed):
            exp = ed["expense"]
            d = exp.date_due if exp.date_due else exp.date_created.date()
            return start_date <= d <= end_date
        approved_expenses = [ed for ed in approved_expenses if _in_range(ed)]

    # Pie chart: member spending
    graph_nodes = []
    for k, v in breakdown["member_map"].items():
        obj = v.get("user_obj")
        has_pic = bool(obj and obj.profile_picture)
        graph_nodes.append({
            "key": k,
            "name": v["name"],
            "is_me": v["is_me"],
            "has_pic": has_pic,
            "avatar_url": obj.ppic_url if has_pic else None,
            "initials": obj.initials if obj else "?",
        })

    member_spending: dict = {}
    project_total = Decimal("0")
    for ed in approved_expenses:
        if ed["expense"].is_buddies_settlement:
            continue
        project_total += ed["total"]
        pk = ed["payer_key"]
        member_spending[pk] = member_spending.get(pk, Decimal("0")) + ed["total"]

    spending_pie = [
        {
            "key": node["key"],
            "name": node["name"],
            "is_me": node["is_me"],
            "spent": float(member_spending.get(node["key"], Decimal("0"))),
            "has_pic": node["has_pic"],
            "avatar_url": node["avatar_url"],
            "initials": node["initials"],
        }
        for node in graph_nodes
    ]

    # Spending over time (line chart)
    spending_over_time = None
    non_settlement = [ed for ed in approved_expenses if not ed["expense"].is_buddies_settlement]
    if non_settlement:
        dated = []
        for ed in non_settlement:
            exp = ed["expense"]
            d = exp.date_due if exp.date_due else exp.date_created.date()
            dated.append((d, ed["payer_key"], float(ed["total"])))

        first_dt = min(r[0] for r in dated)
        last_dt = max(r[0] for r in dated)
        total_days = (last_dt - first_dt).days
        span = total_days + 1
        n_steps = min(100, span)

        all_keys = list(breakdown["member_map"].keys())
        bucket_totals = [0.0] * n_steps
        bucket_by_key = {k: [0.0] * n_steps for k in all_keys}

        for (d, payer_key, amount) in dated:
            idx = min(n_steps - 1, (d - first_dt).days * n_steps // span)
            bucket_totals[idx] += amount
            if payer_key in bucket_by_key:
                bucket_by_key[payer_key][idx] += amount

        labels = []
        for i in range(n_steps):
            end_offset = min(total_days, (i + 1) * span // n_steps - 1)
            labels.append((first_dt + timedelta(days=end_offset)).isoformat())

        line_series = [{"label": "Total", "color": "#888888",
                        "values": [round(v, 2) for v in bucket_totals]}]
        for k, info in breakdown["member_map"].items():
            name = "You" if info["is_me"] else info["name"]
            line_series.append({"label": name,
                                 "values": [round(v, 2) for v in bucket_by_key[k]]})
        spending_over_time = {"labels": labels, "series": line_series}

    # Tag distribution (bar chart)
    tag_dist = None
    if non_settlement:
        from budget.models import Expense as _Exp
        feuser_owned_pks = [
            ed["expense"].pk for ed in non_settlement
            if not ed["expense"].is_dummy and ed["expense"].owning_feuser_id == feuser.pk
        ]
        expense_tag_map: dict = {}
        for exp_obj in _Exp.objects.filter(pk__in=feuser_owned_pks).prefetch_related("tags"):
            expense_tag_map[exp_obj.pk] = [t.title for t in exp_obj.tags.all()]

        tag_amounts: dict = {}
        for ed in non_settlement:
            exp = ed["expense"]
            is_owner = not exp.is_dummy and exp.owning_feuser_id == feuser.pk
            is_participant = any(s["is_me"] for s in ed["participant_shares"])
            if not is_owner and not is_participant:
                continue
            if is_owner:
                tags = expense_tag_map.get(exp.pk, [])
            else:
                tags = overlay_tags.get(exp.pk, [])
            amount = float(ed["total"])
            if tags:
                for title in tags:
                    tag_amounts[title] = tag_amounts.get(title, 0.0) + amount
            else:
                tag_amounts["(untagged)"] = tag_amounts.get("(untagged)", 0.0) + amount

        if tag_amounts:
            tagged = sorted(
                ((k, v) for k, v in tag_amounts.items() if k != "(untagged)"),
                key=lambda x: -x[1],
            )
            untagged = [(k, v) for k, v in tag_amounts.items() if k == "(untagged)"]
            sorted_tags = tagged + untagged
            tag_dist = {
                "labels": [t[0] for t in sorted_tags],
                "values": [round(t[1], 2) for t in sorted_tags],
            }

    return {
        "spending_pie": spending_pie,
        "spending_over_time": spending_over_time,
        "tag_dist": tag_dist,
        "group_total_spending": str(project_total.quantize(Decimal("0.01"))),
    }


@feuser_required
def project_charts_data(request, project_id):
    """AJAX endpoint: returns chart data for a project, filtered by date range."""
    feuser = request.feuser
    project = get_object_or_404(
        Project.objects.prefetch_related("members__feuser", "members__dummy"),
        uid=project_id,
        members__feuser=feuser,
    )

    start_date = None
    end_date = None
    date_from_raw = request.GET.get("date_from")
    date_to_raw   = request.GET.get("date_to")
    if date_from_raw and date_to_raw:
        try:
            from datetime import date as _date_cls
            start_date = _date_cls.fromisoformat(date_from_raw)
            end_date   = _date_cls.fromisoformat(date_to_raw)
        except ValueError:
            pass

    data = _compute_project_charts(feuser, project, start_date, end_date)
    return JsonResponse(data)


_SORT_FIELD_MAP = {
    "date":  lambda ed: (ed["expense"].date_due or date.min),
    "title": lambda ed: ed["expense"].title.lower(),
    "value": lambda ed: ed["expense"].value,
}


@feuser_required
def project_expense_list_partial(request, project_id):
    """
    Returns an HTML fragment with the filtered expense list sections
    (pending + approved) for a project. Used by the filter controls
    on the project detail page via XHR.
    """
    feuser = request.feuser
    project = get_object_or_404(
        Project.objects.prefetch_related("members__feuser", "members__dummy"),
        uid=project_id,
        members__feuser=feuser,
    )
    is_admin = project.admin_feuser_id == feuser.pk

    q = request.GET.get("q", "").strip()
    hide_recurring = request.GET.get("hide_recurring") == "1"
    i_paid = request.GET.get("i_paid") == "1"
    sort_by = request.GET.get("sort_by", "date")
    sort_dir = request.GET.get("sort_dir", "desc")

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

    # Build effective query string including hide_recurring toggle
    effective_q = q
    if hide_recurring:
        effective_q = (effective_q + " recurring=no").strip() if effective_q else "recurring=no"

    # Determine which expense PKs match the query
    if effective_q:
        base_qs = (
            Expense.objects.filter(project=project)
            .select_related("category", "project")
            .prefetch_related("tags", "buddy_spendings__participant_feuser", "buddy_spendings__participant_dummy")
        )
        matching_pks = set(apply_query(base_qs, effective_q, feuser=feuser).values_list("pk", flat=True))
    else:
        matching_pks = None  # no filter: include everything

    breakdown = BuddyQueryService.get_group_full_breakdown(feuser, project)
    overlay_notes, _ = _fetch_overlay_notes(feuser, breakdown)
    _annotate_expense_permissions(feuser, project, breakdown, is_admin, overlay_notes)

    expenses_data = breakdown["expenses"]

    if matching_pks is not None:
        expenses_data = [ed for ed in expenses_data if ed["expense"].pk in matching_pks]
    if start_date and end_date:
        def _in_range(ed):
            exp = ed["expense"]
            d = exp.date_due if exp.date_due else exp.date_created.date()
            return start_date <= d <= end_date
        expenses_data = [ed for ed in expenses_data if _in_range(ed)]
    if i_paid:
        expenses_data = [ed for ed in expenses_data if ed["payer_is_me"]]

    sort_key = _SORT_FIELD_MAP.get(sort_by, _SORT_FIELD_MAP["date"])
    reverse_sort = sort_dir == "desc"
    expenses_data = sorted(expenses_data, key=sort_key, reverse=reverse_sort)

    pending_expenses = [ed for ed in expenses_data if not ed["expense"].buddy_approved]
    approved_expenses = [ed for ed in expenses_data if ed["expense"].buddy_approved]

    project_url = reverse("projects:project_detail", args=[project.uid])
    return render(request, "buddies/project_expense_partial.html", {
        "project": project,
        "group": project,
        "is_admin": is_admin,
        "pending_expenses": pending_expenses,
        "approved_expenses": approved_expenses,
        "currency": feuser.currency,
        "project_url": project_url,
    })


@feuser_required
def project_settings(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(
        Project.objects.prefetch_related("members__feuser", "members__dummy"),
        uid=project_id,
        members__feuser=feuser,
    )
    is_admin = project.admin_feuser_id == feuser.pk
    pending_invites = BuddyQueryService.pending_group_invites_for_group(project) if is_admin else []
    feuser_members = [
        m for m in project.members.all() if m.feuser_id and m.feuser_id != feuser.pk
    ]
    dummy_members = [m for m in project.members.all() if m.dummy_id]
    merge_invites_in_project = BuddyQueryService.pending_merge_invites_incoming_for_project(feuser, project)
    merge_invites_out_project = BuddyQueryService.pending_merge_invites_outgoing_for_project(feuser, project) if is_admin else []
    return render(request, "buddies/project_settings.html", {
        "active_nav": "projects",
        "project": project,
        "group": project,
        "is_admin": is_admin,
        "feuser_members": feuser_members,
        "dummy_members": dummy_members,
        "pending_invites": pending_invites,
        "merge_invites_in_project": merge_invites_in_project,
        "merge_invites_out_project": merge_invites_out_project,
        "currency": feuser.currency,
    })


@feuser_required
def project_export(request, project_id):
    """
    Export project data for the currently selected date range as a
    downloadable ZIP of CSV files: meta.csv (project settings, never
    date-filtered), members.csv (the member roster, never date-filtered),
    expenses.csv and participation_matrix.csv (scoped to the date range),
    and any pictures. See ProjectExportService.write_project_csvs.
    """
    feuser = request.feuser
    project = get_object_or_404(
        Project.objects.select_related("admin_feuser").prefetch_related("members__feuser", "members__dummy"),
        uid=project_id,
        members__feuser=feuser,
    )
    start_date, end_date = resolve_date_range(request, feuser)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        ProjectExportService.write_project_csvs(zf, project, feuser, start_date=start_date, end_date=end_date)

    _name_slug = re.sub(r"[^A-Za-z0-9]+", "_", project.name).strip("_")
    _name_part = f"_{_name_slug}" if _name_slug else ""
    filename = f"project_export{_name_part}_{start_date.isoformat()}_to_{end_date.isoformat()}.zip"
    response = HttpResponse(buf.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@feuser_required
@require_POST
def project_invite_member(request, project_id):
    from django.conf import settings as django_settings
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)

    if project.archived:
        django_messages.error(request, "Cannot invite members to an archived project.")
        return redirect("projects:project_settings", project_id=project_id)

    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("projects:project_settings", project_id=project_id)

    outcome, obj = ProjectService.invite_member(project, feuser, email)
    if outcome == "demo_restricted":
        django_messages.error(request, "Demo accounts cannot invite project members.")
    elif outcome == "invitee_is_demo":
        django_messages.error(request, "That email address is not available.")
    elif outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "self":
        django_messages.error(request, "You cannot invite yourself.")
    elif outcome == "already_member":
        django_messages.info(request, f"{email} is already a member of this project.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated. Share this registration link: {site_url}/register/")
    elif outcome == "onboarding":
        django_messages.success(request, f"A registration and project invitation has been sent to {email}.")
    elif outcome == "invite":
        django_messages.success(request, f"Project invitation sent to {email}.")
    elif outcome == "member":
        django_messages.success(request, f"{email} has been added to the project.")
    return redirect("projects:project_settings", project_id=project_id)


@feuser_required
@require_POST
def project_revoke_invite(request, project_id, token):
    project = get_object_or_404(Project, uid=project_id, admin_feuser=request.feuser)
    ProjectService.revoke_group_invite(token, request.feuser)
    return redirect("projects:project_settings", project_id=project_id)


@feuser_required
def project_remove_member(request, project_id, member_id):
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    member = get_object_or_404(ProjectMember, uid=member_id, group=project)

    if member.feuser_id == feuser.pk:
        django_messages.error(request, "You cannot remove yourself. Transfer admin rights first or delete the project.")
        return redirect("projects:project_detail", project_id=project_id)

    if member.dummy_id:
        dummy = member.dummy

        # Archived project: cannot remove dummies
        if project.archived:
            django_messages.error(request, "Cannot remove offline members from an archived project.")
            return redirect("projects:project_detail", project_id=project_id)

        if dummy.is_archive:
            if BuddyArchiveService.archive_has_expenses(dummy):
                django_messages.error(request, "Achim Archive still holds expenses. Delete all archived expenses first.")
                return redirect("projects:project_detail", project_id=project_id)
            if request.method == "POST" and request.POST.get("confirmed") == "yes":
                dummy.delete()
            return redirect("projects:project_detail", project_id=project_id)

        if request.method == "POST" and request.POST.get("confirmed") == "yes":
            archive_created = ProjectService.delete_group_dummy(project, feuser, dummy)
            url = reverse("projects:project_detail", kwargs={"project_id": project_id})
            if archive_created and not feuser.has_seen_achim_intro:
                url += "?achim=new"
                feuser.has_seen_achim_intro = True
                feuser.save(update_fields=["has_seen_achim_intro"])
            return redirect(url)

        from budget.models import Expense
        net = BuddyArchiveService.get_group_dummy_balance(dummy, project)
        expense_count = (
            BuddySpending.objects.filter(participant_dummy=dummy).values("expense").distinct().count()
            + Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True).count()
        )
        archive_exists = DummyUser.objects.filter(owning_group=project, is_archive=True).exists()

        return render(request, "buddies/project_remove_dummy_confirm.html", {
            "active_nav": "projects",
            "project": project,
            "group": project,
            "member": member,
            "dummy": dummy,
            "net": net,
            "net_abs": abs(net),
            "has_balance": abs(net) > Decimal("0.005"),
            "expense_count": expense_count,
            "archive_exists": archive_exists,
            "currency": feuser.currency,
        })

    # Real feuser removal: archived projects allow this
    if request.method != "POST":
        return redirect("projects:project_detail", project_id=project_id)

    ProjectService.remove_member(project, feuser, member)
    return redirect("projects:project_detail", project_id=project_id)


@feuser_required
def project_archive_wipe(request, project_id, dummy_id):
    """GET: big-warning page. POST with confirmed=yes: wipe all archive expenses."""
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_group=project, is_archive=True)

    if request.method == "POST" and request.POST.get("confirmed") == "yes":
        BuddyArchiveService.wipe_archive(dummy)
        django_messages.success(request, "Achim Archive has been cleared.")
        return redirect("projects:project_detail", project_id=project_id)

    user_impact = BuddyArchiveService.get_user_impact_in_group_archive(feuser, dummy, project)
    participant_count, payer_count = BuddyArchiveService.get_archive_expense_counts_split(dummy)
    expense_count = participant_count + payer_count

    return render(request, "buddies/archive_wipe_confirm.html", {
        "active_nav": "projects",
        "dummy": dummy,
        "project": project,
        "group": project,
        "cancel_url": reverse("projects:project_detail", kwargs={"project_id": project_id}),
        "user_impact": user_impact,
        "user_impact_abs": abs(user_impact),
        "expense_count": expense_count,
        "participant_count": participant_count,
        "payer_count": payer_count,
        "currency": feuser.currency,
    })


@feuser_required
@require_POST
def project_rename_dummy(request, project_id, dummy_id):
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_group=project)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    name = data.get("display_name", "").strip()
    if not name:
        return JsonResponse({"error": "Name required."}, status=400)
    if len(name) > 128:
        return JsonResponse({"error": "Name must be 128 characters or fewer."}, status=400)
    if dummy.is_archive:
        return JsonResponse({"error": "Cannot rename the archive."}, status=400)
    dummy.display_name = name
    dummy.last_mod = timezone.now()
    dummy.save(update_fields=["display_name", "last_mod"])
    return JsonResponse({"display_name": dummy.display_name})


@feuser_required
@require_POST
def project_add_dummy(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)

    if project.archived:
        django_messages.error(request, "Cannot add offline members to an archived project.")
        return redirect("projects:project_detail", project_id=project_id)

    name = request.POST.get("display_name", "").strip()
    if name:
        ProjectService.create_group_dummy(project, feuser, name)
    return redirect("projects:project_settings", project_id=project_id)


@feuser_required
@require_POST
def project_merge_dummy(request, project_id, dummy_id):
    """Merge an offline member into another offline member (immediate) or
    request a merge into an already-linked project member (needs their approval).
    Admin-only, matching all other offline-member management."""
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_group=project, is_archive=False)

    if project.archived:
        django_messages.error(request, "Cannot merge offline members in an archived project.")
        return redirect("projects:project_settings", project_id=project_id)

    if feuser.is_demo:
        django_messages.error(request, "Demo accounts cannot merge buddies.")
        return redirect("projects:project_settings", project_id=project_id)

    target_key = request.POST.get("target_key", "").strip()
    if target_key == "self":
        outcome = ProjectService.merge_group_dummy_into_self(project, feuser, dummy)
        if outcome == "already_pending":
            django_messages.error(request, f"\"{dummy.display_name}\" has a pending merge request. Revoke it first if you want to merge into yourself.")
        else:
            django_messages.success(request, f"Merged \"{dummy.display_name}\" into yourself.")
        return redirect("projects:project_settings", project_id=project_id)

    if len(target_key) < 2 or not target_key[1:].isdigit():
        return redirect("projects:project_settings", project_id=project_id)
    kind, target_id = target_key[0], int(target_key[1:])

    if kind == "d":
        target = get_object_or_404(DummyUser, uid=target_id, owning_group=project, is_archive=False)
        if target.pk == dummy.pk:
            return redirect("projects:project_settings", project_id=project_id)
        outcome = ProjectService.merge_group_dummy_into_dummy_now(project, dummy, target)
        if outcome == "already_pending":
            django_messages.error(request, f"\"{dummy.display_name}\" has a pending merge request. Revoke it first if you want to merge into someone else.")
        else:
            django_messages.success(request, f"Merged \"{dummy.display_name}\" into {target.display_name}.")
    elif kind == "f":
        target_feuser = get_object_or_404(FeUser, pk=target_id, is_active=True)
        outcome, obj = ProjectService.request_group_merge_with_feuser(feuser, project, dummy, target_feuser)
        if outcome == "not_member":
            django_messages.error(request, "You can only request a merge with someone who is already a member of this project.")
        elif outcome == "self":
            django_messages.error(request, "You cannot merge into yourself.")
        elif outcome == "already_pending":
            django_messages.error(request, f"\"{dummy.display_name}\" already has a pending merge request. Revoke it first if you want to send a new one.")
        elif outcome == "demo_restricted":
            django_messages.error(request, "Demo accounts cannot send merge requests.")
        elif outcome == "target_is_demo":
            django_messages.error(request, "Demo accounts cannot be merge targets.")
        elif outcome == "invite":
            django_messages.success(request, f"Merge request sent to {_display_name(target_feuser)}.")
    return redirect("projects:project_settings", project_id=project_id)


@feuser_required
@require_POST
def project_transfer_admin(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    try:
        new_admin_id = int(request.POST.get("new_admin_id", 0))
        new_admin = FeUser.objects.get(pk=new_admin_id, is_active=True)
    except (ValueError, FeUser.DoesNotExist):
        django_messages.error(request, "Invalid user selection.")
        return redirect("projects:project_settings", project_id=project_id)
    ok = ProjectService.transfer_admin(project, feuser, new_admin)
    if not ok:
        django_messages.error(request, "That user is not a project member.")
    return redirect("projects:project_settings", project_id=project_id)


@feuser_required
@require_POST
def project_leave(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(
        Project.objects.prefetch_related("members"),
        uid=project_id,
        members__feuser=feuser,
    )
    if project.admin_feuser_id == feuser.pk:
        # Admin can only leave if there are other real feusers
        other_feuser_members = [
            m for m in project.members.all()
            if m.feuser_id and m.feuser_id != feuser.pk
        ]
        if not other_feuser_members:
            django_messages.error(request, "You are the only member. Use 'Delete Project' instead.")
            return redirect("projects:project_detail", project_id=project_id)
        django_messages.error(request, "You are the project admin. Transfer admin rights to another member before leaving.")
        return redirect("projects:project_detail", project_id=project_id)
    try:
        member = ProjectMember.objects.get(group=project, feuser=feuser)
    except ProjectMember.DoesNotExist:
        return redirect("projects:projects_list")
    ProjectService.remove_member(project, project.admin_feuser, member, notify=False)
    django_messages.success(request, f'You have left the project "{project.name}".')
    return redirect("projects:projects_list")


@feuser_required
def project_delete(request, project_id):
    """Admin deletes the entire project including all data. Requires name confirmation."""
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)

    if request.method == "POST":
        confirmed_name = request.POST.get("confirm_name", "").strip()
        if confirmed_name != project.name:
            django_messages.error(request, "Project name does not match. Deletion cancelled.")
            return redirect("projects:project_settings", project_id=project_id)
        project_name = project.name
        project.delete()
        django_messages.success(request, f'Project "{project_name}" has been deleted.')
        return redirect("projects:projects_list")

    return redirect("projects:project_detail", project_id=project_id)


@feuser_required
@require_POST
def project_archive(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    project.archived = True
    project.save(update_fields=["archived"])
    django_messages.success(request, f'Project "{project.name}" has been archived.')
    return redirect("projects:project_settings", project_id=project_id)


@feuser_required
@require_POST
def project_unarchive(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    project.archived = False
    project.save(update_fields=["archived"])
    django_messages.success(request, f'Project "{project.name}" has been unarchived.')
    return redirect("projects:project_settings", project_id=project_id)


@feuser_required
@require_POST
def reorder_projects(request):
    """Update ProjectMember.sorting for non-archived projects of the requesting user."""
    feuser = request.feuser
    try:
        data = json.loads(request.body)
        order = data.get("order", [])
        if not isinstance(order, list):
            return JsonResponse({"error": "Invalid payload."}, status=400)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    # Validate: only non-archived project IDs belonging to feuser
    valid_ids = set(
        ProjectMember.objects.filter(
            feuser=feuser,
            group__archived=False,
        ).values_list("group_id", flat=True)
    )

    for idx, project_id in enumerate(order, start=1):
        if int(project_id) not in valid_ids:
            continue
        ProjectMember.objects.filter(
            feuser=feuser,
            group_id=project_id,
        ).update(sorting=idx, last_mod=timezone.now())

    return JsonResponse({"ok": True})


@feuser_required
def view_project_invite(request, token):
    try:
        invite = ProjectInvite.objects.select_related(
            "group", "inviting_feuser"
        ).get(token=token)
    except ProjectInvite.DoesNotExist:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if not invite.is_valid():
        invite.delete()
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if request.feuser.email.lower() != invite.invitee_email.lower():
        return render(request, "buddies/invite_wrong_account.html", {
            "active_nav": "buddies",
            "invite": invite,
        })

    return render(request, "buddies/project_invite_view.html", {
        "active_nav": "buddies",
        "invite": invite,
        "inviter_name": _display_name(invite.inviting_feuser),
    })


@feuser_required
@require_POST
def accept_project_invite(request, token):
    project = ProjectService.accept_group_invite(token, request.feuser)
    if project is None:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})
    django_messages.success(request, f'You joined the project "{project.name}".')
    return redirect("projects:project_detail", project_id=project.uid)


@feuser_required
@require_POST
def decline_project_invite(request, token):
    ProjectService.decline_group_invite(token, request.feuser)
    return redirect("projects:projects_list")


@feuser_required
@require_POST
def project_rename(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    name = request.POST.get("name", "").strip()
    if not name:
        django_messages.error(request, "Project name cannot be empty.")
        return redirect("projects:project_settings", project_id=project_id)
    if len(name) > 128:
        django_messages.error(request, "Project name must be 128 characters or fewer.")
        return redirect("projects:project_settings", project_id=project_id)
    description = request.POST.get("description", "").strip()
    project.name = name
    project.description = description
    project.save(update_fields=["name", "description"])
    project.update_lastmod()
    return redirect("projects:project_settings", project_id=project_id)


@feuser_required
def project_picture(request, project_id):
    from PIL import Image
    import io

    project = get_object_or_404(Project, uid=project_id, admin_feuser=request.feuser)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete":
            pic_path = settings.MEDIA_ROOT / "bgpics" / f"{project.pk}.webp"
            pic_path.unlink(missing_ok=True)
            project.group_picture = False
            project.save(update_fields=["group_picture"])
            project.update_lastmod()
        else:
            is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
            upload = request.FILES.get("group_picture")
            if upload:
                try:
                    img = Image.open(upload)
                    img = img.convert("RGB")
                    img.thumbnail((1200, 600), Image.LANCZOS)
                    bgpics_dir = settings.MEDIA_ROOT / "bgpics"
                    bgpics_dir.mkdir(exist_ok=True)
                    buf = io.BytesIO()
                    img.save(buf, "WEBP", quality=82)
                    (bgpics_dir / f"{project.pk}.webp").write_bytes(buf.getvalue())
                    project.group_picture = True
                    project.save(update_fields=["group_picture"])
                    project.update_lastmod()
                    if is_ajax:
                        return JsonResponse({"ok": True})
                except Exception:
                    if is_ajax:
                        return JsonResponse({"ok": False, "error": "Could not process the image."}, status=400)
                    django_messages.error(request, "Could not process the image.")

    return redirect("projects:project_settings", project_id=project.uid)
