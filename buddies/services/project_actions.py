"""
Project management actions with their permission checks, shared by the web views,
the REST API and the MCP server. ProjectService holds the underlying mechanics.
"""
from django.conf import settings
from django.utils import timezone

from ..models import DummyUser, Project, ProjectMember
from ..models.project import AI_PREPROMPT_MAX_LENGTH, PERMISSION_LAXITY_CHOICES
from .archive import BuddyArchiveService
from .group import ProjectService

NAME_MAX_LENGTH = 128


class ProjectError(Exception):
    """A refused project action; `status` is the matching HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def invite_message(outcome: str, email: str) -> tuple[str, str]:
    """(level, text) for a ProjectService.invite_member outcome; level is success, info or error."""
    return {
        "demo_restricted": ("error", "Demo accounts cannot invite project members."),
        "invitee_is_demo": ("error", "That email address is not available."),
        "registration_disabled": ("error", "That email address is not registered and registration is not enabled on this instance."),
        "self": ("error", "You cannot invite yourself."),
        "already_member": ("info", f"{email} is already a member of this project."),
        "onboarding_no_email": ("info", f"Emailing is deactivated. Share this registration link: {getattr(settings, 'SITE_URL', '')}/register/"),
        "onboarding": ("success", f"A registration and project invitation has been sent to {email}."),
        "invite": ("success", f"Project invitation sent to {email}."),
        "member": ("success", f"{email} has been added to the project."),
        "auto_joined": ("success", f"{email} automatically accepts your invitations and has been added to the project."),
    }.get(outcome, ("error", "Could not invite."))


def clean_display_name(name) -> str:
    name = str(name or "").strip()
    if not name:
        raise ProjectError("Name required.")
    if len(name) > NAME_MAX_LENGTH:
        raise ProjectError(f"Name must be {NAME_MAX_LENGTH} characters or fewer.")
    return name


def rename_offline_member(dummy: DummyUser, name) -> DummyUser:
    """Rename an offline member or offline contact; the archive keeps its name."""
    name = clean_display_name(name)
    if dummy.is_archive:
        raise ProjectError("Cannot rename the archive.")
    dummy.display_name = name
    dummy.last_mod = timezone.now()
    dummy.save(update_fields=["display_name", "last_mod"])
    return dummy


def _not_archived(project, action):
    if project.archived:
        raise ProjectError(f"Cannot {action} an archived project.", 403)


def invite(project, admin, email) -> tuple[str, object]:
    """Invite by email; returns ProjectService.invite_member's (outcome, object)."""
    _not_archived(project, "invite members to")
    email = str(email or "").strip()
    if not email:
        raise ProjectError("Email required.")
    return ProjectService.invite_member(project, admin, email)


def add_offline_member(project, admin, name) -> DummyUser:
    _not_archived(project, "add offline members to")
    return ProjectService.create_group_dummy(project, admin, clean_display_name(name))


def remove_member(project, admin, member: ProjectMember) -> bool:
    """
    Remove a member. An offline member's history moves to the project's Achim
    Archive; an empty archive is deleted. Returns True when an archive was created.
    """
    if member.feuser_id == admin.pk:
        raise ProjectError("You cannot remove yourself. Transfer admin rights first or delete the project.")
    if member.feuser_id:
        ProjectService.remove_member(project, admin, member)
        return False
    _not_archived(project, "remove offline members from")
    dummy = member.dummy
    if dummy.is_archive:
        if BuddyArchiveService.archive_has_expenses(dummy):
            raise ProjectError("Achim Archive still holds expenses. Delete all archived expenses first.")
        dummy.delete()
        return False
    return ProjectService.delete_group_dummy(project, admin, dummy)


def update_details(project, feuser, *, name=None, description=None, ai_preprompt=None) -> Project:
    """Change name, description and AI preprompt; None leaves a field unchanged."""
    if not project.can_edit_details(feuser):
        raise ProjectError("You do not have permission to edit this project.", 403)
    if name is not None:
        name = str(name).strip()
        if not name:
            raise ProjectError("Project name cannot be empty.")
        if len(name) > NAME_MAX_LENGTH:
            raise ProjectError(f"Project name must be {NAME_MAX_LENGTH} characters or fewer.")
        project.name = name
    if description is not None:
        project.description = str(description).strip()
    if ai_preprompt is not None:
        ai_preprompt = str(ai_preprompt).strip()
        if len(ai_preprompt) > AI_PREPROMPT_MAX_LENGTH:
            raise ProjectError(f"The AI preprompt must be {AI_PREPROMPT_MAX_LENGTH} characters or fewer.")
        project.ai_preprompt = ai_preprompt
    project.save(update_fields=["name", "description", "ai_preprompt"])
    project.update_lastmod()
    return project


def set_permission_laxity(project, value) -> Project:
    if value not in {choice[0] for choice in PERMISSION_LAXITY_CHOICES}:
        raise ProjectError("Invalid permission setting.")
    project.permission_laxity = value
    project.save(update_fields=["permission_laxity"])
    project.update_lastmod()
    return project


def set_archived(project, archived: bool) -> Project:
    project.archived = archived
    project.save(update_fields=["archived"])
    return project


def transfer_admin(project, admin, new_admin) -> Project:
    if not ProjectService.transfer_admin(project, admin, new_admin):
        raise ProjectError("That user is not a project member.")
    return project


def leave(project, feuser) -> None:
    """A non-admin member leaves; their history moves to an offline member."""
    if project.admin_feuser_id == feuser.pk:
        others = project.members.filter(feuser__isnull=False).exclude(feuser=feuser).exists()
        if not others:
            raise ProjectError("You are the only member. Use 'Delete Project' instead.")
        raise ProjectError("You are the project admin. Transfer admin rights to another member before leaving.")
    member = ProjectMember.objects.filter(group=project, feuser=feuser).first()
    if member:
        ProjectService.remove_member(project, project.admin_feuser, member, notify=False)


def delete(project, confirm_name) -> None:
    """Delete the project with all its data; confirm_name must equal the project name."""
    if str(confirm_name or "").strip() != project.name:
        raise ProjectError("Project name does not match. Deletion cancelled.")
    project.delete()
