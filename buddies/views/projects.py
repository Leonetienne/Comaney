import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages as django_messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from feusers.models import FeUser
from ..models import Project, ProjectInvite, ProjectMember, BuddySpending, DummyUser
from ..services import BuddyArchiveService, ProjectService, BuddyQueryService, _display_name


def _is_solo(project):
    """True if the project has exactly one feuser member and no dummy members."""
    members = list(project.members.all())
    feuser_count = sum(1 for m in members if m.feuser_id)
    dummy_count = sum(1 for m in members if m.dummy_id)
    return feuser_count == 1 and dummy_count == 0


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
        }
        for p in my_projects
    ]

    return render(request, "buddies/projects_list.html", {
        "active_nav": "projects",
        "my_projects": my_projects,
        "project_summaries": project_summaries,
        "currency": feuser.currency,
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
    dummy_pks_in_project = {m.dummy_id for m in project.members.all() if m.dummy_id}

    for exp_data in breakdown["expenses"]:
        exp = exp_data["expense"]
        exp_data["creditor_approval_needed"] = False
        exp_data["admin_approval_needed"] = False

        if not exp.buddy_approved:
            for share in exp_data["participant_shares"]:
                if share["key"] == feuser_key:
                    exp_data["creditor_approval_needed"] = True
                    break
            if is_admin and not exp_data["creditor_approval_needed"]:
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

        # Archived project: block destructive actions except confirming in-flight settlements
        if project.archived:
            exp_data["can_delete"] = False
            exp_data["can_unlink"] = False
            exp_data["can_edit"] = False
            # Allow confirming/rejecting pending settlements (in-flight)
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

    raw_graph_json = json.dumps({
        "nodes": graph_nodes,
        "links": [
            {"from": f, "to": t, "amount": float(a)}
            for (f, t), a in raw_flows.items()
            if a > Decimal("0.005") and f != t
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

    raw_debts_json = json.dumps([
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
            {"key": f"d{m.dummy.pk}", "name": m.dummy.display_name + " (offline member)", "is_me": False, "is_dummy": True}
            for m in dummy_members
        ],
    ])

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

    member_spending: dict[str, Decimal] = {}
    project_total_spending = Decimal("0")
    for exp_data in approved_expenses:
        if exp_data["expense"].is_buddies_settlement:
            continue
        project_total_spending += exp_data["total"]
        pk = exp_data["payer_key"]
        member_spending[pk] = member_spending.get(pk, Decimal("0")) + exp_data["payer_amount"]
        for share in exp_data["participant_shares"]:
            key = share["key"]
            member_spending[key] = member_spending.get(key, Decimal("0")) + share["amount"]

    spending_pie_json = json.dumps([
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
    ])

    return render(request, "buddies/project_detail.html", {
        "active_nav": "projects",
        "project": project,
        "group": project,  # backward compat for template snippets
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
        "spending_pie_json": spending_pie_json,
        "project_total_spending": project_total_spending,
        "group_total_spending": project_total_spending,  # backward compat
        "has_multiple_members": len(breakdown["member_map"]) > 1,
        "currency": feuser.currency,
    })


@feuser_required
@require_POST
def project_invite_member(request, project_id):
    from django.conf import settings as django_settings
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)

    if project.archived:
        django_messages.error(request, "Cannot invite members to an archived project.")
        return redirect("projects:project_detail", project_id=project_id)

    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("projects:project_detail", project_id=project_id)

    outcome, obj = ProjectService.invite_member(project, feuser, email)
    if outcome == "registration_disabled":
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
    return redirect("projects:project_detail", project_id=project_id)


@feuser_required
@require_POST
def project_revoke_invite(request, project_id, token):
    project = get_object_or_404(Project, uid=project_id, admin_feuser=request.feuser)
    ProjectService.revoke_group_invite(token, request.feuser)
    return redirect("projects:project_detail", project_id=project_id)


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
    dummy.save(update_fields=["display_name"])
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
    return redirect("projects:project_detail", project_id=project_id)


@feuser_required
@require_POST
def project_send_merge(request, project_id, dummy_id):
    from django.conf import settings as django_settings
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_group=project)
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("projects:project_detail", project_id=project_id)
    outcome, obj = ProjectService.send_group_dummy_merge_invite(project, feuser, dummy, email)
    if outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated. Share this link: {site_url}/register/")
    elif outcome in ("onboarding", "invite"):
        django_messages.success(request, f"Merge invitation sent to {email}.")
    return redirect("projects:project_detail", project_id=project_id)


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
        return redirect("projects:project_detail", project_id=project_id)
    ok = ProjectService.transfer_admin(project, feuser, new_admin)
    if not ok:
        django_messages.error(request, "That user is not a project member.")
    return redirect("projects:project_detail", project_id=project_id)


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
            return redirect("projects:project_detail", project_id=project_id)
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
    return redirect("projects:project_detail", project_id=project_id)


@feuser_required
@require_POST
def project_unarchive(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    project.archived = False
    project.save(update_fields=["archived"])
    django_messages.success(request, f'Project "{project.name}" has been unarchived.')
    return redirect("projects:project_detail", project_id=project_id)


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
        ).update(sorting=idx)

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
    return redirect("buddies:my_buddies")


@feuser_required
@require_POST
def project_rename(request, project_id):
    feuser = request.feuser
    project = get_object_or_404(Project, uid=project_id, admin_feuser=feuser)
    name = request.POST.get("name", "").strip()
    if not name:
        django_messages.error(request, "Project name cannot be empty.")
        return redirect("projects:project_detail", project_id=project_id)
    if len(name) > 128:
        django_messages.error(request, "Project name must be 128 characters or fewer.")
        return redirect("projects:project_detail", project_id=project_id)
    description = request.POST.get("description", "").strip()
    project.name = name
    project.description = description
    project.save(update_fields=["name", "description"])
    project.update_lastmod()
    return redirect("projects:project_detail", project_id=project_id)


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
                except Exception:
                    django_messages.error(request, "Could not process the image.")

    return redirect("projects:project_detail", project_id=project.uid)
