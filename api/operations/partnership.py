from buddies.models import CatalogPartnershipInvite
from buddies.services import partnership_actions
from buddies.services.partnership_actions import OPEN_STATUSES, PartnershipError
from feusers.models import FeUser

from . import confirm
from .common import ID, person_name
from ..registry import READ, WRITE, NotFound, OpError, operation

_MAPPING = {
    "type": "object",
    "description": "Own title -> inviter title, or null to drop it. Every unmatched own title must appear.",
    "additionalProperties": {"type": ["string", "null"]},
}


def _run(fn):
    try:
        return fn()
    except PartnershipError as exc:
        raise OpError(str(exc), exc.status)


@operation(
    "partnership_get", concern="partnership", access=READ, method="GET", path="partnership/",
    description=(
        "The feuser's Catalog Partnership: partners share one category and tag catalog, so every change "
        "to a category or tag reaches all of them. Shows partners, open invitations and any invitation to the feuser."
    ),
)
def partnership_get(ctx, args):
    feuser = ctx.feuser
    membership = partnership_actions.membership_of(feuser)
    incoming = CatalogPartnershipInvite.objects.filter(invitee_email=feuser.email, status__in=OPEN_STATUSES).select_related("inviter")
    data = {
        "in_partnership": bool(membership and membership.onboarding_complete),
        "incoming_invites": [{"id": i.pk, "from": person_name(i.inviter)} for i in incoming],
        "partners": [],
        "outgoing_invites": [],
    }
    if membership:
        data["partners"] = [
            {"id": m.feuser_id, "name": person_name(m.feuser), "onboarded": m.onboarding_complete}
            for m in membership.partnership.memberships.exclude(feuser=feuser).select_related("feuser")
        ]
        data["outgoing_invites"] = [
            {"id": i.pk, "email": i.invitee_email}
            for i in membership.partnership.invites.filter(status__in=OPEN_STATUSES)
        ]
    return data


@operation(
    "partnership_invite", concern="partnership", access=WRITE, method="POST", path="partnership/invites/",
    description="Invite a contact or fellow project member (feuser_id) into the feuser's Catalog Partnership.",
    params={"feuser_id": ID}, required=["feuser_id"], status=201,
)
def partnership_invite(ctx, args):
    invitee = FeUser.objects.filter(pk=args["feuser_id"], is_active=True).first()
    if invitee is None:
        raise NotFound("User not found.")
    invite = _run(lambda: partnership_actions.invite(ctx.feuser, invitee))
    return {"id": invite.pk, "invited": person_name(invitee)}


@operation(
    "partnership_invite_cancel", concern="partnership", access=WRITE, method="DELETE", path="partnership/invites/<int:id>/",
    description="Withdraw an open invitation of the feuser's partnership.", params={"id": ID}, required=["id"], status=204,
)
def partnership_invite_cancel(ctx, args):
    invite = CatalogPartnershipInvite.objects.filter(pk=args["id"]).first()
    if invite is None:
        raise NotFound("Invitation not found.")
    _run(lambda: partnership_actions.cancel_invite(ctx.feuser, invite.token))
    return None


@operation(
    "partnership_remove_partner", concern="partnership", access=WRITE, method="DELETE", path="partnership/partners/<int:feuser_id>/",
    description="Remove a partner from the partnership; they keep a copy of the catalog.",
    params={"feuser_id": ID}, required=["feuser_id"], destructive=True, status=204,
)
def partnership_remove_partner(ctx, args):
    _run(lambda: partnership_actions.kick(ctx.feuser, FeUser.objects.filter(pk=args["feuser_id"]).first()))
    return None


@operation(
    "partnership_leave", concern="partnership", access=WRITE, method="POST", path="partnership/leave/",
    description="Leave the partnership; the feuser keeps a copy of the catalog.", destructive=True,
)
def partnership_leave(ctx, args):
    _run(lambda: partnership_actions.leave(ctx.feuser))
    return {"left": True}


def _invite(ctx):
    return _run(lambda: partnership_actions.open_invite(ctx.feuser))


@operation(
    "partnership_onboarding_state", concern="partnership", access=READ, method="GET", path="partnership/onboarding/",
    description=(
        "For the open invitation to the feuser: the inviter's catalog and the feuser's own tags and categories, "
        "split into matched (same title) and unmatched. Joining replaces the feuser's catalog with the inviter's, "
        "so every unmatched title needs a target or an explicit drop."
    ),
)
def partnership_onboarding_state(ctx, args):
    invite = _invite(ctx)
    return {"invite_id": invite.pk, "from": person_name(invite.inviter), **partnership_actions.onboarding_state(ctx.feuser, invite)}


def _maps(ctx, invite, args):
    tag_map, cat_map = args.get("tag_map") or {}, args.get("category_map") or {}
    _run(lambda: partnership_actions.check_complete_mapping(
        partnership_actions.onboarding_state(ctx.feuser, invite), tag_map, cat_map,
    ))
    return tag_map, cat_map


def _state(ctx, invite, tag_map, cat_map) -> str:
    """Fingerprint of both catalogs and the mappings, so a preview token goes stale on any change."""
    return confirm.fingerprint(invite.pk, partnership_actions.onboarding_state(ctx.feuser, invite), sorted(tag_map.items()), sorted(cat_map.items()))


@operation(
    "partnership_onboarding_preview", concern="partnership", access=READ, method="POST", path="partnership/onboarding/preview/",
    description=(
        "Check complete mappings and show what joining would do to each own title and how many expenses, recurring "
        "expenses and overlays carry them. Changes nothing; returns a confirm_token (10 minutes) for "
        "partnership_onboarding_apply."
    ),
    params={"tag_map": _MAPPING, "category_map": _MAPPING},
)
def partnership_onboarding_preview(ctx, args):
    invite = _invite(ctx)
    tag_map, cat_map = _maps(ctx, invite, args)
    preview = partnership_actions.onboarding_preview(ctx.feuser, invite, tag_map, cat_map)
    token = confirm.issue(ctx, "partnership_onboarding", _state(ctx, invite, tag_map, cat_map))
    return {**preview, "confirm_token": token}


@operation(
    "partnership_onboarding_apply", concern="partnership", access=WRITE, method="POST", path="partnership/onboarding/apply/",
    description=(
        "Join the partnership with exactly the previewed mappings: the feuser's catalog is replaced and their "
        "records remapped. Refused when anything changed since the preview."
    ),
    params={"tag_map": _MAPPING, "category_map": _MAPPING, "confirm_token": {"type": "string"}},
    required=["confirm_token"], destructive=True,
)
def partnership_onboarding_apply(ctx, args):
    invite = _invite(ctx)
    tag_map, cat_map = _maps(ctx, invite, args)
    confirm.check(ctx, args["confirm_token"], "partnership_onboarding", _state(ctx, invite, tag_map, cat_map))
    partnership_actions.apply_onboarding(ctx.feuser, invite, tag_map, cat_map)
    return {"joined": True}


@operation(
    "partnership_onboarding_decline", concern="partnership", access=WRITE, method="POST", path="partnership/onboarding/decline/",
    description="Decline the open partnership invitation to the feuser.",
)
def partnership_onboarding_decline(ctx, args):
    partnership_actions.decline(ctx.feuser, _invite(ctx))
    return {"declined": True}
