from decimal import Decimal

from buddies.models import ContactInvite
from buddies.services import BuddyLifecycleService, BuddyQueryService, contact_actions
from buddies.services.contact_actions import ContactError
from buddies.services.project_actions import rename_offline_member
from feusers.models import FeUser

from .common import ID, person_name
from ..registry import READ, WRITE, NotFound, OpError, operation

_PERSON = {
    "type": "object",
    "properties": {"type": {"type": "string", "enum": ["feuser", "offline"]}, "id": {"type": "integer"}},
    "required": ["type", "id"],
}


def _run(fn):
    try:
        return fn()
    except ContactError as exc:
        raise OpError(str(exc), exc.status)


def person_key(person) -> str:
    """{"type": "feuser"|"offline", "id": n} -> the "f<id>"/"d<id>" key the settlement services use."""
    if not isinstance(person, dict) or person.get("type") not in ("feuser", "offline"):
        raise OpError("A person needs type feuser or offline and an id.")
    try:
        return ("f" if person["type"] == "feuser" else "d") + str(int(person["id"]))
    except (KeyError, TypeError, ValueError):
        raise OpError("A person needs type feuser or offline and an id.")


@operation(
    "contacts_list", concern="contacts", access=READ, method="GET", path="contacts/",
    description=(
        "Contacts and offline contacts with the balance of personal shared expenses "
        "(positive: they owe the feuser), auto-accept flags, projects in common, and open outgoing invitations."
    ),
)
def contacts_list(ctx, args):
    feuser = ctx.feuser
    contacts = []
    for row in BuddyQueryService.get_all_debts_unified(feuser):
        person = row["feuser"] or row["dummy"]
        entry = {
            "type": "feuser" if row["type"] == "feuser" else "offline",
            "id": person.pk,
            "name": row["display_name"],
            "balance": str(row["net"].quantize(Decimal("0.01"))),
            "shared_in": [s for s in row["sources"] if s != "Contact"],
        }
        if row["type"] == "feuser":
            entry.update(
                email=person.email, link_id=row["link_uid"],
                i_auto_accept=row["i_auto_accept"], they_auto_accept=row["they_auto_accept"],
            )
        contacts.append(entry)
    return {
        "currency": feuser.currency,
        "contacts": contacts,
        "outgoing_invites": [
            {"id": inv.pk, "email": inv.invitee_email, "expires_at": inv.expires_at.isoformat()}
            for inv in BuddyQueryService.pending_invites_outgoing(feuser)
        ],
    }


@operation(
    "contacts_invite", concern="contacts", access=WRITE, method="POST", path="contacts/invites/",
    description=(
        "Invite someone as a contact by email, or a known feuser (e.g. a fellow project member) by feuser_id. "
        "They get an email and must accept."
    ),
    params={"email": {"type": "string"}, "feuser_id": ID}, status=201,
)
def contacts_invite(ctx, args):
    if args.get("feuser_id"):
        invitee = FeUser.objects.filter(pk=args["feuser_id"], is_active=True).first()
        if invitee is None:
            raise NotFound("User not found.")
        outcome, _ = _run(lambda: contact_actions.invite_feuser(ctx.feuser, invitee))
        email = invitee.email
    elif args.get("email"):
        email = args["email"]
        outcome, _ = _run(lambda: contact_actions.invite_by_email(ctx.feuser, email))
    else:
        raise OpError("Give email or feuser_id.")
    level, text = contact_actions.invite_message(outcome, email)
    if level == "error":
        raise OpError(text)
    return {"outcome": outcome, "message": text}


@operation(
    "contacts_invite_revoke", concern="contacts", access=WRITE, method="DELETE", path="contacts/invites/<int:id>/",
    description="Withdraw an own outgoing contact invitation.", params={"id": ID}, required=["id"], status=204,
)
def contacts_invite_revoke(ctx, args):
    invite = ContactInvite.objects.filter(pk=args["id"], inviter=ctx.feuser).first()
    if invite is None:
        raise NotFound("Invitation not found.")
    BuddyLifecycleService.revoke_invite(invite.token, ctx.feuser)
    return None


@operation(
    "contacts_invite_respond", concern="contacts", access=WRITE, method="POST", path="contacts/invites/<int:id>/respond/",
    description="Accept or decline an incoming contact invitation (ids from pending_list).",
    params={"id": ID, "accept": {"type": "boolean"}}, required=["id", "accept"],
)
def contacts_invite_respond(ctx, args):
    invite = ContactInvite.objects.filter(pk=args["id"], invitee_email__iexact=ctx.feuser.email).select_related("inviter").first()
    if invite is None:
        raise NotFound("Invitation not found.")
    inviter = invite.inviter
    if not args["accept"]:
        BuddyLifecycleService.decline_invite(invite.token, ctx.feuser)
        return {"declined": True}
    if BuddyLifecycleService.accept_invite(invite.token, ctx.feuser) is None:
        raise OpError("The invitation has expired.")
    return {"accepted": True, "contact": {"type": "feuser", "id": inviter.pk, "name": person_name(inviter)}}


@operation(
    "contacts_remove", concern="contacts", access=WRITE, method="DELETE", path="contacts/<int:link_id>/",
    description="End a contact link (link_id from contacts_list). Shared history stays.",
    params={"link_id": ID}, required=["link_id"], destructive=True, status=204,
)
def contacts_remove(ctx, args):
    _run(lambda: contact_actions.remove_contact(ctx.feuser, contact_actions.own_link(ctx.feuser, args["link_id"])))
    return None


@operation(
    "contacts_set_auto_accept", concern="contacts", access=WRITE, method="PUT", path="contacts/<int:link_id>/auto-accept/",
    description=(
        "Automatically accept expenses, settlements and project invitations this contact records. "
        "Enabling also accepts everything of theirs that is pending."
    ),
    params={"link_id": ID, "enabled": {"type": "boolean"}}, required=["link_id", "enabled"],
)
def contacts_set_auto_accept(ctx, args):
    link = _run(lambda: contact_actions.own_link(ctx.feuser, args["link_id"]))
    result, message = contact_actions.set_auto_accept(ctx.feuser, link, args["enabled"])
    return {"enabled": args["enabled"], "accepted_entries": result.entries, "joined_projects": result.projects, "message": message}


@operation(
    "contacts_add_offline", concern="contacts", access=WRITE, method="POST", path="contacts/offline/",
    description="Add an offline contact: someone without an account to split personal expenses with.",
    params={"name": {"type": "string"}}, required=["name"], status=201,
)
def contacts_add_offline(ctx, args):
    dummy = _run(lambda: contact_actions.add_offline_contact(ctx.feuser, args["name"]))
    return {"type": "offline", "id": dummy.pk, "name": dummy.display_name}


@operation(
    "contacts_rename_offline", concern="contacts", access=WRITE, method="PATCH", path="contacts/offline/<int:id>/",
    description="Rename an offline contact.", params={"id": ID, "name": {"type": "string"}}, required=["id", "name"],
)
def contacts_rename_offline(ctx, args):
    dummy = _run(lambda: contact_actions.own_offline_contact(ctx.feuser, args["id"]))
    _run(lambda: rename_offline_member(dummy, args["name"]))
    return {"type": "offline", "id": dummy.pk, "name": dummy.display_name}


@operation(
    "contacts_remove_offline", concern="contacts", access=WRITE, method="DELETE", path="contacts/offline/<int:id>/",
    description=(
        "Remove an offline contact; their history moves to the feuser's Achim Archive. "
        "With an open balance pass accept_balance=true."
    ),
    params={"id": ID, "accept_balance": {"type": "boolean"}}, required=["id"], destructive=True,
)
def contacts_remove_offline(ctx, args):
    feuser = ctx.feuser
    dummy = _run(lambda: contact_actions.own_offline_contact(feuser, args["id"]))
    if not dummy.is_archive and not args.get("accept_balance"):
        net = BuddyQueryService.get_net_debt(feuser, contact_dummy=dummy)
        if abs(net) > Decimal("0.05"):
            raise OpError(f"{dummy.display_name} has an open balance of {net:.2f} {feuser.currency}; pass accept_balance=true to remove anyway.")
    archive_created = _run(lambda: contact_actions.remove_offline_contact(feuser, dummy))
    return {"removed": True, "archive_created": archive_created}
