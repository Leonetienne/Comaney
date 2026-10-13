from decimal import Decimal

from buddies.models import DummyUser, Project, ProjectInvite, ProjectMember
from buddies.models.project import PERMISSION_LAXITY_ADMIN_ONLY, PERMISSION_LAXITY_MEMBERS
from buddies.services import BuddyQueryService, ProjectService, approvals, project_actions
from buddies.services.approvals import ApprovalError
from buddies.services.project_actions import ProjectError
from feusers.models import FeUser

from .common import ID, person_name
from ..registry import READ, WRITE, NotFound, OpError, operation

_LAXITY = {"admin_only": PERMISSION_LAXITY_ADMIN_ONLY, "members": PERMISSION_LAXITY_MEMBERS}
_LAXITY_NAMES = {v: k for k, v in _LAXITY.items()}


def _run(fn):
    try:
        return fn()
    except (ProjectError, ApprovalError) as exc:
        raise OpError(str(exc), exc.status)


def _money(value) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def member_project(feuser, uid) -> Project:
    project = Project.objects.filter(uid=uid, members__feuser=feuser).distinct().first()
    if project is None:
        raise NotFound("Project not found.")
    return project


def admin_project(feuser, uid) -> Project:
    project = member_project(feuser, uid)
    if project.admin_feuser_id != feuser.pk:
        raise OpError("Only the project admin can do this.", 403)
    return project


def _member_json(member, project):
    if member.feuser_id:
        return {
            "member_id": member.uid, "type": "feuser", "id": member.feuser_id, "name": person_name(member.feuser),
            "is_admin": member.feuser_id == project.admin_feuser_id,
        }
    return {
        "member_id": member.uid, "type": "offline", "id": member.dummy_id, "name": member.dummy.display_name,
        "is_archive": member.dummy.is_archive,
    }


def _project_json(feuser, project, summary=None):
    data = {
        "id": project.uid,
        "name": project.name,
        "description": project.description,
        "archived": project.archived,
        "is_admin": project.admin_feuser_id == feuser.pk,
    }
    if summary:
        data["my_balance"] = _money(summary["net"])
        data["total_spending"] = _money(summary["group_total_spending"])
    return data


@operation(
    "projects_list", concern="projects", access=READ, method="GET", path="projects/",
    description=(
        "The feuser's projects with their balance in each (positive: others owe the feuser) "
        "and total spending, plus incoming project invitations."
    ),
)
def projects_list(ctx, args):
    feuser = ctx.feuser
    summaries = {s["group"].uid: s for s in BuddyQueryService.get_group_summaries_for_feuser(feuser)}
    return {
        "currency": feuser.currency,
        "projects": [_project_json(feuser, p, summaries.get(p.uid)) for p in BuddyQueryService.get_projects_for_feuser(feuser)],
        "incoming_invites": [
            {"id": inv.pk, "project": inv.group.name, "from": person_name(inv.inviting_feuser)}
            for inv in BuddyQueryService.pending_group_invites_incoming(feuser)
        ],
    }


@operation(
    "projects_get", concern="projects", access=READ, method="GET", path="projects/<int:id>/",
    description=(
        "A project with members, settings, the feuser's simplified debts in it (positive: that person owes "
        "the feuser) and, for the admin, open invitations. Its expenses: expenses_list with q=project=<name>."
    ),
    params={"id": ID}, required=["id"],
)
def projects_get(ctx, args):
    feuser = ctx.feuser
    project = member_project(feuser, args["id"])
    summary = next((s for s in BuddyQueryService.get_group_summaries_for_feuser(feuser) if s["group"].uid == project.uid), None)
    data = _project_json(feuser, project, summary)
    members = project.members.select_related("feuser", "dummy").all()
    data.update(
        currency=feuser.currency,
        ai_preprompt=project.ai_preprompt,
        permission_laxity=_LAXITY_NAMES.get(project.permission_laxity),
        can_edit_details=project.can_edit_details(feuser),
        members=[_member_json(m, project) for m in members],
        my_debts=[
            {"person": {"type": "feuser" if isinstance(d["person"], FeUser) else "offline", "id": d["person"].pk,
                        "name": person_name(d["person"]) if isinstance(d["person"], FeUser) else d["person"].display_name},
             "net": _money(d["net"])}
            for d in BuddyQueryService.get_group_simplified_debts(feuser, project)
        ],
    )
    if project.admin_feuser_id == feuser.pk:
        data["outgoing_invites"] = [
            {"id": inv.pk, "email": inv.invitee_email} for inv in BuddyQueryService.pending_group_invites_for_group(project)
        ]
    return data


@operation(
    "projects_create", concern="projects", access=WRITE, method="POST", path="projects/",
    description="Create a project with the feuser as admin and only member.",
    params={"name": {"type": "string"}, "description": {"type": "string"}}, required=["name"], status=201,
)
def projects_create(ctx, args):
    name = str(args["name"]).strip()
    if not name or len(name) > project_actions.NAME_MAX_LENGTH:
        raise OpError(f"'name' must be 1 to {project_actions.NAME_MAX_LENGTH} characters.")
    project = ProjectService.create_group(ctx.feuser, name, description=args.get("description", ""))
    return _project_json(ctx.feuser, project)


@operation(
    "projects_update", concern="projects", access=WRITE, method="PATCH", path="projects/<int:id>/",
    description=(
        "Change a project; only given fields change. name, description and ai_preprompt (instructions "
        "AI Express follows for this project) need edit rights; permission_laxity and archived are admin only. "
        "An archived project blocks changes to its expenses."
    ),
    params={
        "id": ID,
        "name": {"type": "string"},
        "description": {"type": "string"},
        "ai_preprompt": {"type": "string", "description": "Up to 500 characters."},
        "permission_laxity": {"type": "string", "enum": list(_LAXITY), "description": "Who may edit name, description, preprompt."},
        "archived": {"type": "boolean"},
    },
    required=["id"],
)
def projects_update(ctx, args):
    feuser = ctx.feuser
    project = member_project(feuser, args["id"])
    if any(k in args for k in ("name", "description", "ai_preprompt")):
        _run(lambda: project_actions.update_details(
            project, feuser, name=args.get("name"), description=args.get("description"), ai_preprompt=args.get("ai_preprompt"),
        ))
    if "permission_laxity" in args or "archived" in args:
        if project.admin_feuser_id != feuser.pk:
            raise OpError("Only the project admin can change permissions or archive the project.", 403)
        if "permission_laxity" in args:
            _run(lambda: project_actions.set_permission_laxity(project, _LAXITY[args["permission_laxity"]]))
        if "archived" in args:
            project_actions.set_archived(project, args["archived"])
    return projects_get(ctx, {"id": project.uid})


@operation(
    "projects_delete", concern="projects", access=WRITE, method="DELETE", path="projects/<int:id>/",
    description="Delete a project with all its expenses. Admin only; confirm_name must equal the project name.",
    params={"id": ID, "confirm_name": {"type": "string"}}, required=["id", "confirm_name"], destructive=True, status=204,
)
def projects_delete(ctx, args):
    project = admin_project(ctx.feuser, args["id"])
    _run(lambda: project_actions.delete(project, args["confirm_name"]))
    return None


@operation(
    "projects_invite", concern="projects", access=WRITE, method="POST", path="projects/<int:id>/invites/",
    description=(
        "Invite someone by email, or a contact by feuser_id. Contacts who auto-accept the feuser's "
        "invitations join at once; others get an email. Admin only."
    ),
    params={"id": ID, "email": {"type": "string"}, "feuser_id": ID}, required=["id"], status=201,
)
def projects_invite(ctx, args):
    project = admin_project(ctx.feuser, args["id"])
    email = args.get("email")
    if args.get("feuser_id"):
        invitee = FeUser.objects.filter(pk=args["feuser_id"], is_active=True).first()
        if invitee is None:
            raise NotFound("User not found.")
        email = invitee.email
    if not email:
        raise OpError("Give email or feuser_id.")
    outcome, _ = _run(lambda: project_actions.invite(project, ctx.feuser, email))
    level, text = project_actions.invite_message(outcome, email)
    if level == "error":
        raise OpError(text)
    return {"outcome": outcome, "message": text}


@operation(
    "projects_invite_revoke", concern="projects", access=WRITE, method="DELETE",
    path="projects/<int:id>/invites/<int:invite_id>/",
    description="Withdraw an open invitation of the project. Admin only.",
    params={"id": ID, "invite_id": ID}, required=["id", "invite_id"], status=204,
)
def projects_invite_revoke(ctx, args):
    project = admin_project(ctx.feuser, args["id"])
    invite = ProjectInvite.objects.filter(pk=args["invite_id"], group=project).first()
    if invite is None:
        raise NotFound("Invitation not found.")
    ProjectService.revoke_group_invite(invite.token, ctx.feuser)
    return None


@operation(
    "projects_invite_respond", concern="projects", access=WRITE, method="POST", path="projects/invites/<int:invite_id>/respond/",
    description="Accept or decline an incoming project invitation (ids from projects_list or pending_list).",
    params={"invite_id": ID, "accept": {"type": "boolean"}}, required=["invite_id", "accept"],
)
def projects_invite_respond(ctx, args):
    invite = ProjectInvite.objects.filter(pk=args["invite_id"], invitee_email__iexact=ctx.feuser.email).first()
    if invite is None:
        raise NotFound("Invitation not found.")
    if not args["accept"]:
        ProjectService.decline_group_invite(invite.token, ctx.feuser)
        return {"declined": True}
    project = ProjectService.accept_group_invite(invite.token, ctx.feuser)
    if project is None:
        raise OpError("The invitation has expired.")
    return {"accepted": True, "project": _project_json(ctx.feuser, project)}


@operation(
    "projects_add_offline_member", concern="projects", access=WRITE, method="POST", path="projects/<int:id>/offline-members/",
    description="Add an offline member (someone without an account). Admin only.",
    params={"id": ID, "name": {"type": "string"}}, required=["id", "name"], status=201,
)
def projects_add_offline_member(ctx, args):
    project = admin_project(ctx.feuser, args["id"])
    dummy = _run(lambda: project_actions.add_offline_member(project, ctx.feuser, args["name"]))
    return {"type": "offline", "id": dummy.pk, "name": dummy.display_name}


@operation(
    "projects_rename_offline_member", concern="projects", access=WRITE, method="PATCH",
    path="projects/<int:id>/offline-members/<int:member_id>/",
    description="Rename an offline member (member_id = their offline id from projects_get). Admin only.",
    params={"id": ID, "member_id": ID, "name": {"type": "string"}}, required=["id", "member_id", "name"],
)
def projects_rename_offline_member(ctx, args):
    project = admin_project(ctx.feuser, args["id"])
    dummy = DummyUser.objects.filter(pk=args["member_id"], owning_group=project).first()
    if dummy is None:
        raise NotFound("Offline member not found.")
    _run(lambda: project_actions.rename_offline_member(dummy, args["name"]))
    return {"type": "offline", "id": dummy.pk, "name": dummy.display_name}


@operation(
    "projects_remove_member", concern="projects", access=WRITE, method="DELETE",
    path="projects/<int:id>/members/<int:member_id>/",
    description=(
        "Remove a member (member_id from projects_get). A removed feuser's history stays under an offline "
        "stand-in; an offline member's history moves to the project's Achim Archive. Admin only."
    ),
    params={"id": ID, "member_id": ID}, required=["id", "member_id"], destructive=True,
)
def projects_remove_member(ctx, args):
    project = admin_project(ctx.feuser, args["id"])
    member = ProjectMember.objects.filter(uid=args["member_id"], group=project).first()
    if member is None:
        raise NotFound("Member not found.")
    archive_created = _run(lambda: project_actions.remove_member(project, ctx.feuser, member))
    return {"removed": True, "archive_created": archive_created}


@operation(
    "projects_transfer_admin", concern="projects", access=WRITE, method="POST", path="projects/<int:id>/transfer-admin/",
    description="Hand admin rights to another member feuser. Admin only.",
    params={"id": ID, "feuser_id": ID}, required=["id", "feuser_id"],
)
def projects_transfer_admin(ctx, args):
    project = admin_project(ctx.feuser, args["id"])
    new_admin = FeUser.objects.filter(pk=args["feuser_id"], is_active=True).first()
    if new_admin is None:
        raise NotFound("User not found.")
    _run(lambda: project_actions.transfer_admin(project, ctx.feuser, new_admin))
    return {"admin": {"id": new_admin.pk, "name": person_name(new_admin)}}


@operation(
    "projects_leave", concern="projects", access=WRITE, method="POST", path="projects/<int:id>/leave/",
    description="Leave a project; the admin must transfer admin rights first.",
    params={"id": ID}, required=["id"], destructive=True,
)
def projects_leave(ctx, args):
    project = member_project(ctx.feuser, args["id"])
    _run(lambda: project_actions.leave(project, ctx.feuser))
    return {"left": True}


@operation(
    "projects_expense_unlink", concern="projects", access=WRITE, method="POST",
    path="projects/<int:id>/expenses/<int:expense_id>/unlink/",
    description="Take an expense out of the project; it stays with its owner as a personal expense.",
    params={"id": ID, "expense_id": ID}, required=["id", "expense_id"],
)
def projects_expense_unlink(ctx, args):
    _run(lambda: approvals.unlink_project_expense(ctx.feuser, args["id"], args["expense_id"]))
    return {"unlinked": True}


@operation(
    "projects_expense_delete", concern="projects", access=WRITE, method="DELETE",
    path="projects/<int:id>/expenses/<int:expense_id>/",
    description=(
        "Delete an expense of the project: own expenses, and for the admin offline-paid expenses. "
        "Approved settlements stay."
    ),
    params={"id": ID, "expense_id": ID}, required=["id", "expense_id"], destructive=True, status=204,
)
def projects_expense_delete(ctx, args):
    _run(lambda: approvals.delete_project_expense(ctx.feuser, args["id"], args["expense_id"]))
    return None
