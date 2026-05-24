"""
CatalogPartnership sync service.

All tag/category mutations by a partner propagate here to every other
onboarding-complete partner. Auto-removal logic for lost connections lives here too.
"""
import logging

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_sync_targets(actor_feuser):
    """Return memberships of all partners who have completed onboarding."""
    from buddies.models import CatalogPartnershipMembership
    try:
        my_membership = actor_feuser.catalog_membership
    except CatalogPartnershipMembership.DoesNotExist:
        return []
    if not my_membership.onboarding_complete:
        return []
    return list(
        my_membership.partnership.memberships
        .filter(onboarding_complete=True)
        .exclude(feuser=actor_feuser)
        .select_related("feuser")
    )


# ---------------------------------------------------------------------------
# Tag sync
# ---------------------------------------------------------------------------

def sync_tag_create(title: str, actor_feuser) -> None:
    from budget.models import Tag
    for m in _get_sync_targets(actor_feuser):
        Tag.objects.get_or_create(owning_feuser=m.feuser, title=title)


def sync_tag_rename(old_title: str, new_title: str, actor_feuser) -> None:
    from budget.models import Tag
    from django.utils import timezone
    for m in _get_sync_targets(actor_feuser):
        Tag.objects.filter(owning_feuser=m.feuser, title=old_title).update(
            title=new_title, last_mod=timezone.now()
        )


def sync_tag_delete(title: str, actor_feuser) -> None:
    from budget.models import Tag
    for m in _get_sync_targets(actor_feuser):
        Tag.objects.filter(owning_feuser=m.feuser, title=title).delete()


# ---------------------------------------------------------------------------
# Category sync
# ---------------------------------------------------------------------------

def sync_category_create(title: str, actor_feuser) -> None:
    from budget.models import Category
    for m in _get_sync_targets(actor_feuser):
        Category.objects.get_or_create(owning_feuser=m.feuser, title=title)


def sync_category_rename(old_title: str, new_title: str, actor_feuser) -> None:
    from budget.models import Category
    from django.utils import timezone
    for m in _get_sync_targets(actor_feuser):
        Category.objects.filter(owning_feuser=m.feuser, title=old_title).update(
            title=new_title, last_mod=timezone.now()
        )


def sync_category_delete(title: str, actor_feuser) -> None:
    from budget.models import Category
    for m in _get_sync_targets(actor_feuser):
        Category.objects.filter(owning_feuser=m.feuser, title=title).delete()


# ---------------------------------------------------------------------------
# Membership lifecycle
# ---------------------------------------------------------------------------

def dissolve_if_solo(partnership) -> None:
    """Delete the partnership entity if only 1 (or 0) members remain."""
    if partnership.memberships.count() <= 1:
        partnership.memberships.all().delete()
        partnership.delete()


def remove_member(feuser, reason: str = "left") -> None:
    """
    Remove feuser from their partnership and send notifications.
    reason: "left" | "kicked" | "disconnected"
    """
    from buddies.models import CatalogPartnershipMembership
    try:
        membership = feuser.catalog_membership
    except CatalogPartnershipMembership.DoesNotExist:
        return

    partnership = membership.partnership
    remaining = list(
        partnership.memberships.exclude(feuser=feuser).select_related("feuser")
    )
    membership.delete()

    from buddies.services.partnership_email import notify_partner_event
    if reason == "kicked":
        notify_partner_event(feuser, "kicked_self")
        for m in remaining:
            notify_partner_event(m.feuser, "partner_kicked", kicked=feuser)
    elif reason == "left":
        for m in remaining:
            notify_partner_event(m.feuser, "partner_left", left=feuser)
    elif reason == "disconnected":
        for m in remaining:
            notify_partner_event(m.feuser, "partner_disconnected", removed=feuser)

    dissolve_if_solo(partnership)


# ---------------------------------------------------------------------------
# Auto-removal on lost connection
# ---------------------------------------------------------------------------

def _has_connection_to_any_partner(feuser, partnership) -> bool:
    """True if feuser shares a BuddyLink or Project with at least one partner."""
    from buddies.models import BuddyLink, ProjectMember
    from django.db.models import Q

    partner_ids = list(
        partnership.memberships.exclude(feuser=feuser).values_list("feuser_id", flat=True)
    )
    if not partner_ids:
        return False

    has_buddy = BuddyLink.objects.filter(
        Q(user_a=feuser, user_b_id__in=partner_ids) |
        Q(user_b=feuser, user_a_id__in=partner_ids)
    ).exists()
    if has_buddy:
        return True

    feuser_project_ids = set(
        ProjectMember.objects.filter(feuser=feuser).values_list("group_id", flat=True)
    )
    if not feuser_project_ids:
        return False
    return ProjectMember.objects.filter(
        group_id__in=feuser_project_ids, feuser_id__in=partner_ids
    ).exists()


def check_auto_remove(feuser) -> None:
    """Auto-remove feuser from their partnership if no connection to any partner remains."""
    from buddies.models import CatalogPartnershipMembership
    try:
        membership = feuser.catalog_membership
    except CatalogPartnershipMembership.DoesNotExist:
        return
    if not _has_connection_to_any_partner(feuser, membership.partnership):
        _log.info("Auto-removing %s from partnership: no connections remain", feuser)
        remove_member(feuser, reason="disconnected")
