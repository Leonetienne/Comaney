"""
Catalog Partnership actions with their permission checks, shared by the web views,
the REST API and the MCP server. partnership.py holds catalog sync and remapping.
"""
from collections import Counter

from django.db import transaction
from django.db.models import Q

from ..models import (
    CatalogPartnership, CatalogPartnershipInvite, CatalogPartnershipMembership, ContactLink, ProjectMember,
)
from . import partnership
from .partnership_email import notify_partner_event

OPEN_STATUSES = [CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP]


class PartnershipError(Exception):
    """A refused partnership action; `status` is the matching HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def has_mutual_connection(a, b) -> bool:
    """True if the two feusers share a contact link or at least one project."""
    if ContactLink.objects.filter(Q(user_a=a, user_b=b) | Q(user_a=b, user_b=a)).exists():
        return True
    a_projects = set(ProjectMember.objects.filter(feuser=a).values_list("group_id", flat=True))
    return ProjectMember.objects.filter(feuser=b, group_id__in=a_projects).exists()


def membership_of(feuser):
    try:
        return feuser.catalog_membership
    except CatalogPartnershipMembership.DoesNotExist:
        return None


def invite(feuser, invitee) -> CatalogPartnershipInvite:
    """Invite a connected feuser, creating feuser's partnership on first use, and notify them."""
    if feuser.is_demo:
        raise PartnershipError("Demo accounts cannot use Catalog Partnerships.", 403)
    if invitee == feuser:
        raise PartnershipError("Cannot invite yourself.")
    if invitee.is_demo:
        raise PartnershipError("Cannot invite a demo account as a partner.", 403)
    if not has_mutual_connection(feuser, invitee):
        raise PartnershipError("No mutual connection with this user.", 403)
    if membership_of(invitee) is not None:
        raise PartnershipError("This user is already in a Catalog Partnership.", 409)
    if CatalogPartnershipInvite.objects.filter(invitee_email=invitee.email, status__in=OPEN_STATUSES).exists():
        raise PartnershipError("An invite is already pending for this user.", 409)

    membership = membership_of(feuser)
    if membership is None:
        group = CatalogPartnership.objects.create()
        CatalogPartnershipMembership.objects.create(partnership=group, feuser=feuser, onboarding_complete=True)
    else:
        group = membership.partnership
    created = CatalogPartnershipInvite.objects.create(partnership=group, inviter=feuser, invitee_email=invitee.email)
    notify_partner_event(invitee, "invite_sent", invite=created)
    return created


def open_invite(feuser, token=None) -> CatalogPartnershipInvite:
    """The open invitation addressed to feuser (by token if given). Raises PartnershipError."""
    qs = CatalogPartnershipInvite.objects.filter(invitee_email=feuser.email, status__in=OPEN_STATUSES)
    if token is not None:
        qs = qs.filter(token=token)
    found = qs.select_related("inviter", "partnership").order_by("-pk").first()
    if found is None:
        raise PartnershipError("No open partnership invitation for this account.", 404)
    return found


def onboarding_state(feuser, invite_obj) -> dict:
    """Inviter's catalog and feuser's own titles split into matched and unmatched."""
    from budget.models import Category, Tag

    master = invite_obj.inviter
    master_tags = sorted(Tag.objects.filter(owning_feuser=master).values_list("title", flat=True))
    master_cats = sorted(Category.objects.filter(owning_feuser=master).values_list("title", flat=True))
    my_tags = sorted(Tag.objects.filter(owning_feuser=feuser).values_list("title", flat=True))
    my_cats = sorted(Category.objects.filter(owning_feuser=feuser).values_list("title", flat=True))
    return {
        "master_tags": master_tags,
        "master_categories": master_cats,
        "matched_tags": [t for t in my_tags if t in set(master_tags)],
        "unmatched_tags": [t for t in my_tags if t not in set(master_tags)],
        "matched_categories": [c for c in my_cats if c in set(master_cats)],
        "unmatched_categories": [c for c in my_cats if c not in set(master_cats)],
    }


def check_complete_mapping(state, tag_map: dict, cat_map: dict) -> None:
    """Every unmatched title must be mapped to an inviter title or explicitly dropped (None)."""
    problems = []
    for kind, unmatched, mapping, targets in (
        ("tag", state["unmatched_tags"], tag_map, set(state["master_tags"])),
        ("category", state["unmatched_categories"], cat_map, set(state["master_categories"])),
    ):
        for title in unmatched:
            if title not in mapping:
                problems.append(f"{kind} '{title}' is neither mapped nor dropped")
            elif mapping[title] is not None and mapping[title] not in targets:
                problems.append(f"{kind} '{title}' maps to '{mapping[title]}', which the inviter does not have")
    if problems:
        raise PartnershipError("Incomplete mapping: " + "; ".join(problems) + ".")


def onboarding_preview(feuser, invite_obj, tag_map: dict, cat_map: dict) -> dict:
    """What applying these mappings would change, per own title, without changing anything."""
    plan = partnership.plan_onboarding_catalog(feuser, invite_obj.inviter, tag_map, cat_map)
    tag_uses, cat_uses = Counter(), Counter()
    kinds = Counter()
    for record, _tags, _cat in plan.records:
        kinds[type(record).__name__] += 1
        for tag in record.tags.all():
            tag_uses[tag.title] += 1
        if record.category:
            cat_uses[record.category.title] += 1

    def rows(own_titles, master_titles, mapping, uses):
        out = []
        for title in own_titles:
            target = title if title in master_titles else mapping.get(title)
            out.append({"title": title, "becomes": target, "records": uses[title]})
        return out

    state = onboarding_state(feuser, invite_obj)
    return {
        "tags": rows(state["matched_tags"] + state["unmatched_tags"], set(state["master_tags"]), tag_map, tag_uses),
        "categories": rows(
            state["matched_categories"] + state["unmatched_categories"], set(state["master_categories"]), cat_map, cat_uses,
        ),
        "records": {"expenses": kinds["Expense"], "recurring_expenses": kinds["ScheduledExpense"], "overlays": kinds["ExpenseDataOverlay"]},
        "note": "Your catalog is replaced by the inviter's; records keep only titles that exist there after mapping.",
    }


def apply_onboarding(feuser, invite_obj, tag_map: dict, cat_map: dict) -> None:
    """Replace feuser's catalog with the partnership's, remap their records, join, and notify partners."""
    with transaction.atomic():
        partnership.apply_onboarding_catalog(feuser, invite_obj.inviter, tag_map=tag_map, cat_map=cat_map)
        invite_obj.status = CatalogPartnershipInvite.STATUS_ACTIVE
        invite_obj.save(update_fields=["status"])
        membership, _ = CatalogPartnershipMembership.objects.get_or_create(
            feuser=feuser, defaults={"partnership": invite_obj.partnership, "onboarding_complete": False},
        )
        membership.partnership = invite_obj.partnership
        membership.onboarding_complete = True
        membership.save(update_fields=["partnership", "onboarding_complete"])

    notify_partner_event(invite_obj.inviter, "invite_accepted", invitee=feuser)
    others = (
        invite_obj.partnership.memberships.exclude(feuser=feuser).exclude(feuser=invite_obj.inviter).select_related("feuser")
    )
    for m in others:
        notify_partner_event(m.feuser, "new_partner_joined", joined=feuser)


def decline(feuser, invite_obj) -> None:
    invite_obj.status = CatalogPartnershipInvite.STATUS_DECLINED
    invite_obj.save(update_fields=["status"])
    notify_partner_event(invite_obj.inviter, "invite_declined", invitee=feuser)
    partnership.dissolve_if_solo(invite_obj.partnership)


def cancel_invite(actor, token) -> None:
    """A partner withdraws an open invitation of their partnership."""
    membership = membership_of(actor)
    if membership is None:
        raise PartnershipError("You are not in a partnership.", 403)
    found = CatalogPartnershipInvite.objects.filter(
        token=token, partnership=membership.partnership, status__in=OPEN_STATUSES,
    ).first()
    if found is None:
        raise PartnershipError("Invitation not found.", 404)
    found.status = CatalogPartnershipInvite.STATUS_DECLINED
    found.save(update_fields=["status"])


def kick(actor, target) -> None:
    membership = membership_of(actor)
    if membership is None:
        raise PartnershipError("You are not in a partnership.", 403)
    target_membership = membership_of(target) if target else None
    if target_membership is None:
        raise PartnershipError("Partner not found.", 404)
    if target_membership.partnership_id != membership.partnership_id:
        raise PartnershipError("Not in the same partnership.", 403)
    if target == actor:
        raise PartnershipError("Use 'leave' to remove yourself.")
    partnership.remove_member(target, reason="kicked")


def leave(feuser) -> None:
    if membership_of(feuser) is None:
        raise PartnershipError("You are not in a partnership.", 403)
    partnership.remove_member(feuser, reason="left")
