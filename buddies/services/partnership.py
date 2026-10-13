"""
CatalogPartnership sync service.

All tag/category mutations by a partner propagate here to every other
onboarding-complete partner. Auto-removal logic for lost connections lives here too.
"""
import logging
from typing import NamedTuple

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
    """True if feuser shares a ContactLink or Project with at least one partner."""
    from buddies.models import ContactLink, ProjectMember
    from django.db.models import Q

    partner_ids = list(
        partnership.memberships.exclude(feuser=feuser).values_list("feuser_id", flat=True)
    )
    if not partner_ids:
        return False

    has_buddy = ContactLink.objects.filter(
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


# ---------------------------------------------------------------------------
# Onboarding apply
# ---------------------------------------------------------------------------

def _mapped_title(title: str, master_titles: set, mapping: dict) -> str | None:
    """Title in the partnership catalog that `title` ends up as; None means dropped."""
    if title in master_titles:
        return title
    target = mapping.get(title)
    return target if target in master_titles else None


class OnboardingPlan(NamedTuple):
    master_tags: list
    master_cats: list
    records: list  # (record, new tag titles, new category title)


def plan_onboarding_catalog(feuser, master, tag_map: dict, cat_map: dict) -> OnboardingPlan:
    """
    Read-only: what every record carrying feuser's labels (own expenses, own
    recurring expenses, own overlays) ends up labelled with under these maps.
    Maps are {source title: target title or None (drop)}; unmapped titles are dropped.
    """
    from budget.models import Category, Expense, ExpenseDataOverlay, ScheduledExpense, Tag

    master_tags = list(Tag.objects.filter(owning_feuser=master))
    master_cats = list(Category.objects.filter(owning_feuser=master))
    master_tag_titles = {t.title for t in master_tags}
    master_cat_titles = {c.title for c in master_cats}

    labelled = [
        Expense.objects.filter(owning_feuser=feuser),
        ScheduledExpense.objects.filter(owning_feuser=feuser),
        ExpenseDataOverlay.objects.filter(feuser=feuser).select_related("expense"),
    ]
    records = []
    for qs in labelled:
        for record in qs.select_related("category").prefetch_related("tags"):
            tag_titles = {_mapped_title(t.title, master_tag_titles, tag_map) for t in record.tags.all()}
            tag_titles.discard(None)
            cat_title = (
                _mapped_title(record.category.title, master_cat_titles, cat_map)
                if record.category else None
            )
            records.append((record, tag_titles, cat_title))
    return OnboardingPlan(master_tags, master_cats, records)


def apply_onboarding_catalog(feuser, master, tag_map: dict, cat_map: dict) -> None:
    """
    Replace feuser's catalog with a copy of master's and remap every record
    carrying feuser's labels as plan_onboarding_catalog() describes. Run inside a transaction.
    """
    from budget.models import Category, ExpenseDataOverlay, Tag
    from budget.services import upsert_overlay

    plan = plan_onboarding_catalog(feuser, master, tag_map, cat_map)

    Tag.objects.filter(owning_feuser=feuser).delete()
    Category.objects.filter(owning_feuser=feuser).delete()
    new_tags, new_cats = {}, {}
    for tag in plan.master_tags:
        new_tags.setdefault(tag.title, Tag.objects.create(owning_feuser=feuser, title=tag.title))
    for cat in plan.master_cats:
        new_cats.setdefault(cat.title, Category.objects.create(owning_feuser=feuser, title=cat.title))

    for record, tag_titles, cat_title in plan.records:
        category = new_cats.get(cat_title)
        tags = [new_tags[t] for t in sorted(tag_titles)]
        if isinstance(record, ExpenseDataOverlay):
            # upsert_overlay deletes an overlay left without category, tags and note
            upsert_overlay(record.expense, feuser, category, tags, record.note)
            continue
        if category:
            record.category = category
            record.save(update_fields=["category"])
        record.tags.set(tags)
