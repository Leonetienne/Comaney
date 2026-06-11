"""Overlay helpers: personal per-participant category/tags on buddy expenses."""
from __future__ import annotations

from django.utils import timezone


def upsert_overlay(expense, feuser, category, tags: list, note: str | None = None):
    """
    Create or update an overlay for feuser on expense.
    Empty/whitespace-only note is stored as None (inherit expense.note).
    Deletes (or skips creating) if category, tags, and note are all empty.
    Returns the overlay instance or None.
    """
    from .models import ExpenseDataOverlay

    note = note.strip() if note and note.strip() else None
    if not category and not tags and note is None:
        ExpenseDataOverlay.objects.filter(expense=expense, feuser=feuser).delete()
        return None

    overlay, _ = ExpenseDataOverlay.objects.get_or_create(
        expense=expense,
        feuser=feuser,
        defaults={"category": category, "note": note},
    )
    overlay.category = category
    overlay.note = note
    overlay.last_mod = timezone.now()
    overlay.save(update_fields=["category", "note", "last_mod"])
    overlay.tags.set(tags)
    return overlay


def snapshot_overlay(expense, feuser):
    """
    Snapshot the expense's current category/tags into an overlay for feuser.
    Only creates an overlay when there is at least one non-empty value.
    Note is not snapshotted (it's personal; the expense note belongs to the owner).
    Returns the overlay or None.
    """
    tags = list(expense.tags.all())
    return upsert_overlay(expense, feuser, expense.category, tags)


def apply_overlay(overlay, expense):
    """
    Copy overlay's category/tags directly onto expense (M2M set + category assign).
    Does NOT save the expense — caller must call expense.save().
    Deletes the overlay after applying.
    """
    expense.category = overlay.category
    expense.tags.set(list(overlay.tags.all()))
    overlay.delete()


def _same_catalog_partnership(a, b) -> bool:
    """True if a and b are both members of the same onboarding-complete
    CatalogPartnership -- the only case where their tag catalogs are actually
    guaranteed to be in sync (buddies.services.partnership syncs tags/categories
    between partners the moment onboarding completes)."""
    from buddies.models import CatalogPartnershipMembership
    try:
        a_membership = a.catalog_membership
    except CatalogPartnershipMembership.DoesNotExist:
        return False
    try:
        b_membership = b.catalog_membership
    except CatalogPartnershipMembership.DoesNotExist:
        return False
    return (
        a_membership.onboarding_complete
        and b_membership.onboarding_complete
        and a_membership.partnership_id == b_membership.partnership_id
    )


def create_participant_overlays(expense):
    """
    For each real-user participant of expense, auto-create an overlay if a
    match is found:
      - category: unconditionally, if the participant has their own category
        with the same title as the expense's category. A wrong category
        match is just wrong -- easy to notice and fix.
      - tags: ONLY when the participant and the owner are in the same Catalog
        Partnership (see _same_catalog_partnership), where their tag catalogs
        are guaranteed to actually be the same set. Matching tags by title
        for unrelated feusers is unsafe: a coincidental match ("Restaurant"
        vs "Restaurante") assigns one plausible-looking tag while silently
        dropping every other tag the expense should have gotten, and -- because
        the overlay is no longer empty -- the expense stops showing up on the
        Unclassified Expenses page (budget/unclassified.py) even though it's
        still missing most of its real tags.
    Only creates an overlay when there is at least one match.
    Skips participants who already have an overlay (preserves explicit overlays).
    """
    from .models import Category, Tag, ExpenseDataOverlay

    expense_tags = list(expense.tags.all())
    expense_category = expense.category

    already_has_overlay = set(
        ExpenseDataOverlay.objects.filter(expense=expense)
        .values_list("feuser_id", flat=True)
    )

    for bs in expense.buddy_spendings.filter(participant_feuser__isnull=False).select_related("participant_feuser"):
        p = bs.participant_feuser
        if p.pk in already_has_overlay:
            continue

        matched_category = None
        if expense_category:
            try:
                matched_category = Category.objects.get(owning_feuser=p, title=expense_category.title)
            except Category.DoesNotExist:
                pass

        matched_tags = []
        if expense_tags and _same_catalog_partnership(expense.owning_feuser, p):
            for tag in expense_tags:
                try:
                    matched_tags.append(Tag.objects.get(owning_feuser=p, title=tag.title))
                except Tag.DoesNotExist:
                    pass

        if matched_category or matched_tags:
            upsert_overlay(expense, p, matched_category, matched_tags)
