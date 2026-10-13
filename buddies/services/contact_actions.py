"""
Contact management actions with their permission checks, shared by the web views,
the REST API and the MCP server. BuddyLifecycleService holds the underlying mechanics.
"""
from django.conf import settings

from ..models import ContactLink, DummyUser
from .lifecycle import BuddyLifecycleService
from .project_actions import ProjectError, clean_display_name
from .query import BuddyQueryService
from .trust import BuddyTrustService

ContactError = ProjectError


def invite_message(outcome: str, email: str) -> tuple[str, str]:
    """(level, text) for a BuddyLifecycleService.invite_actual outcome; level is success, info or error."""
    return {
        "demo_restricted": ("error", "Demo accounts cannot invite contacts."),
        "invitee_is_demo": ("error", "That email address is not available."),
        "registration_disabled": ("error", "That email address is not registered and registration is not enabled on this instance."),
        "self": ("error", "You cannot invite yourself."),
        "already_contacts": ("info", f"{email} is already one of your contacts."),
        "onboarding_no_email": ("info", f"Emailing is deactivated for this instance. Give this link to your friend: {getattr(settings, 'SITE_URL', '')}/register/"),
        "invite": ("success", f"An invitation has been sent to {email}."),
        "onboarding": ("success", f"An invitation has been sent to {email}."),
        "link": ("success", f"{email} is now one of your contacts."),
    }.get(outcome, ("error", "Could not invite."))


def invite_by_email(feuser, email) -> tuple[str, object]:
    email = str(email or "").strip()
    if not email:
        raise ContactError("Email required.")
    return BuddyLifecycleService.invite_actual(feuser, email)


def invite_feuser(feuser, invitee) -> tuple[str, object]:
    """Invite a known feuser (e.g. a fellow project member) as a contact."""
    if feuser.is_demo:
        raise ContactError("Demo accounts cannot invite contacts.", 403)
    if invitee == feuser:
        raise ContactError("Cannot invite yourself.")
    if invitee.is_demo:
        raise ContactError("Cannot invite a demo account as a contact.", 403)
    if BuddyQueryService.are_contacts(feuser, invitee):
        raise ContactError("This user is already one of your contacts.", 409)
    if BuddyQueryService.has_pending_invite_to(feuser, invitee):
        raise ContactError("An invite is already pending for this user.", 409)
    outcome, obj = BuddyLifecycleService.invite_actual(feuser, invitee.email)
    if outcome not in ("invite", "link", "onboarding", "onboarding_no_email"):
        raise ContactError("Could not send invite.")
    return outcome, obj


def own_link(feuser, link_id) -> ContactLink:
    link = ContactLink.objects.filter(uid=link_id).first()
    if link is None or feuser.pk not in (link.user_a_id, link.user_b_id):
        raise ContactError("Contact not found.", 404)
    return link


def remove_contact(feuser, link) -> None:
    """End a contact link; their shared history stays."""
    BuddyLifecycleService.kick_actual(feuser, link.other(feuser), has_debt_warning_accepted=True)


def set_auto_accept(feuser, link, enabled: bool):
    """Toggle auto-accept of the other side's entries; returns (AutoAcceptResult, message)."""
    other = link.other(feuser)
    result = BuddyTrustService.set_auto_accept(feuser, other, enabled)
    from . import _display_name
    name = _display_name(other)
    if enabled:
        msg = f"You now automatically accept entries from {name}."
        if result.entries:
            msg += f" {result.entries} pending entr{'y' if result.entries == 1 else 'ies'} accepted."
        if result.projects:
            msg += f" You joined {result.projects} project{'' if result.projects == 1 else 's'}."
    else:
        msg = f"You no longer automatically accept entries from {name}."
    return result, msg


def add_offline_contact(feuser, name) -> DummyUser:
    return BuddyLifecycleService.add_dummy(feuser, clean_display_name(name))


def own_offline_contact(feuser, dummy_id) -> DummyUser:
    dummy = DummyUser.objects.filter(uid=dummy_id, owning_feuser=feuser).first()
    if dummy is None:
        raise ContactError("Offline contact not found.", 404)
    return dummy


def remove_offline_contact(feuser, dummy, *, balance_warning_accepted=True) -> bool:
    """
    Remove an offline contact; their history moves to the personal Achim Archive.
    An empty archive is deleted. Returns True when an archive was created.
    Without balance_warning_accepted an open balance keeps the contact.
    """
    from .archive import BuddyArchiveService

    if dummy.is_archive:
        if BuddyArchiveService.archive_has_expenses(dummy):
            raise ContactError("Achim Archive still holds expenses. Delete all archived expenses first.")
        dummy.delete()
        return False
    result = BuddyLifecycleService.kick_dummy(feuser, dummy, has_debt_warning_accepted=balance_warning_accepted)
    return bool(result.get("archive_created"))
