"""
Unclassified Expenses: finds expenses missing a category and/or tags, from the
current feuser's own point of view.

An expense is unclassified for a feuser when:
  - it's their own expense (owning_feuser == feuser) and its category or tags
    are empty, or
  - the feuser is a participant (BuddySpending) on someone else's expense, and
    the feuser's own ExpenseDataOverlay for it has no category and no tags
    (the owner's classification of that same expense is irrelevant to this
    check -- it's evaluated purely from the feuser's own overlay).
Settlement expenses are never unclassified, regardless of state. Neither are
savings deposits/withdrawals (TransactionType.SAVINGS_DEPOSIT/SAVINGS_WITHDRAWAL)
-- moving money between your own accounts isn't the kind of spend a
category/tag classifies meaningfully.

This is a fourth place implementing the same "own vs overlay" visibility split
as budget/query_parser.py's `_tag_q`/`_cat_q`/`visible_tag_titles` and
budget/dashboard_cards.py's `_compute_chart` (see CLAUDE.md).
"""
from __future__ import annotations

from .models import Category, Expense, ExpenseDataOverlay, Tag, TransactionType

# Never surfaced as unclassified, regardless of category/tags state: a
# settlement isn't a real spend, and a savings movement isn't the kind of
# thing a category/tag meaningfully classifies.
_EXCLUDED_TYPES = [TransactionType.SAVINGS_DEPOSIT, TransactionType.SAVINGS_WITHDRAWAL]


def category_tag_catalog(feuser) -> tuple[list[dict], list[dict]]:
    """
    The feuser's own category/tag catalog as (categories, tags), each a list of
    {"uid": int, "title": str}. Shared by the unclassified-expenses page (for
    the category dropdown / tags combobox) and budget.unclassified_ai (for the
    AI system prompt) -- both need the same closed catalog, so this is the one
    place that builds it for this feature.
    """
    categories = list(
        Category.objects.filter(owning_feuser=feuser).order_by("title").values("uid", "title")
    )
    tags = list(
        Tag.objects.filter(owning_feuser=feuser).order_by("title").values("uid", "title")
    )
    return categories, tags


def _problem(has_category: bool, has_tags: bool) -> str | None:
    if not has_category and not has_tags:
        return "Category and Tags missing"
    if not has_category:
        return "Category missing"
    if not has_tags:
        return "Tags missing"
    return None


def _build_row(expense: Expense, kind: str, overlay: ExpenseDataOverlay | None) -> dict:
    """
    Shape a single row from an already-fetched Expense (+ its overlay, for a
    foreign expense). Used both for the bulk list and for single-expense
    lookups (save, AI solve), so the two never drift on what a row looks like.
    """
    if kind == "own":
        category = expense.category
        tags = list(expense.tags.all())
        owner_category_title = None
        owner_tag_titles = None
        owner_name = None
    else:
        category = overlay.category if overlay else None
        tags = list(overlay.tags.all()) if overlay else []
        owner_category_title = expense.category.title if expense.category else None
        owner_tag_titles = [t.title for t in expense.tags.all()]
        owner = expense.owning_feuser
        owner_name = f"{owner.first_name} {owner.last_name}".strip() or owner.email

    return {
        "expense_uid": expense.pk,
        "kind": kind,
        "title": expense.title,
        "value": str(expense.value),
        "type": expense.type,
        "payee": expense.payee,
        "note": expense.note,
        "date_due": expense.date_due.isoformat() if expense.date_due else None,
        "project_title": expense.project.name if expense.project_id else None,
        "category_uid": category.pk if category else None,
        "category_title": category.title if category else None,
        "tag_uids": [t.pk for t in tags],
        "tag_titles": [t.title for t in tags],
        "problem": _problem(category is not None, bool(tags)),
        "owner_category_title": owner_category_title,
        "owner_tag_titles": owner_tag_titles,
        # For a foreign row: who this expense actually belongs to, so the UI
        # can say "From <project>" / "From <owner>" -- never a bare "shared",
        # which reads as if the current feuser were the one sharing it out.
        "owner_name": owner_name,
    }


def resolve_expense_kind(feuser, expense_uid) -> tuple[Expense | None, str | None, ExpenseDataOverlay | None]:
    """
    Returns (expense, kind, overlay) for expense_uid from feuser's point of
    view: kind is "own" (feuser is the owner) or "foreign" (feuser is a
    BuddySpending participant on someone else's expense; overlay is their own
    ExpenseDataOverlay, or None if they don't have one yet). Returns
    (None, None, None) if feuser has no access to this expense at all.
    """
    expense = (
        Expense.objects.filter(pk=expense_uid, owning_feuser=feuser)
        .select_related("category", "project")
        .prefetch_related("tags")
        .first()
    )
    if expense is not None:
        return expense, "own", None

    from buddies.models import BuddySpending
    if not BuddySpending.objects.filter(expense_id=expense_uid, participant_feuser=feuser).exists():
        return None, None, None

    expense = (
        Expense.objects.filter(pk=expense_uid)
        .select_related("category", "owning_feuser", "project")
        .prefetch_related("tags")
        .first()
    )
    if expense is None:
        return None, None, None
    overlay = (
        ExpenseDataOverlay.objects.filter(expense=expense, feuser=feuser)
        .select_related("category")
        .prefetch_related("tags")
        .first()
    )
    return expense, "foreign", overlay


def get_unclassified_row(feuser, expense_uid) -> dict | None:
    """Row for a single expense, or None if feuser has no access to it (this
    does NOT check whether it's still unclassified -- callers check `problem`
    on the returned row themselves)."""
    expense, kind, overlay = resolve_expense_kind(feuser, expense_uid)
    if expense is None:
        return None
    return _build_row(expense, kind, overlay)


def _own_rows(feuser) -> list[dict]:
    qs = (
        Expense.objects.filter(owning_feuser=feuser, is_buddies_settlement=False)
        .exclude(type__in=_EXCLUDED_TYPES)
        .select_related("category", "project")
        .prefetch_related("tags")
        .order_by("-date_created")
    )
    return [
        row for expense in qs
        if (row := _build_row(expense, "own", None))["problem"] is not None
    ]


def _foreign_rows(feuser) -> list[dict]:
    from buddies.models import BuddySpending

    expense_ids = (
        BuddySpending.objects.filter(participant_feuser=feuser)
        .values_list("expense_id", flat=True)
        .distinct()
    )
    qs = (
        Expense.objects.filter(pk__in=expense_ids, is_buddies_settlement=False)
        .exclude(owning_feuser=feuser)
        .exclude(type__in=_EXCLUDED_TYPES)
        .select_related("category", "owning_feuser", "project")
        .prefetch_related("tags")
        .order_by("-date_created")
    )
    overlays = {
        o.expense_id: o
        for o in ExpenseDataOverlay.objects.filter(
            feuser=feuser, expense_id__in=expense_ids
        ).select_related("category").prefetch_related("tags")
    }
    return [
        row for expense in qs
        if (row := _build_row(expense, "foreign", overlays.get(expense.pk)))["problem"] is not None
    ]


def get_unclassified_rows(feuser) -> list[dict]:
    """Returns one dict per unclassified expense (own or foreign), newest first."""
    # expense_uid (BigAutoField) is monotonically increasing with date_created,
    # so it doubles as a stable recency key across the two merged sub-lists.
    return sorted(_own_rows(feuser) + _foreign_rows(feuser), key=lambda r: r["expense_uid"], reverse=True)


def count_unclassified_expenses(feuser) -> int:
    """
    Lean count (no row-building) for the nav badge, which is computed on
    every page load app-wide via budget_base.html -- must stay a couple of
    plain COUNT queries, not the full get_unclassified_rows() row shaping.
    """
    from django.db.models import Q

    own = (
        Expense.objects.filter(owning_feuser=feuser, is_buddies_settlement=False)
        .exclude(type__in=_EXCLUDED_TYPES)
        .filter(Q(category__isnull=True) | Q(tags__isnull=True))
        .distinct()
        .count()
    )

    from buddies.models import BuddySpending

    expense_ids = (
        BuddySpending.objects.filter(participant_feuser=feuser)
        .values_list("expense_id", flat=True)
        .distinct()
    )
    # A foreign expense is classified for feuser only when their overlay has
    # BOTH a category and at least one tag; anything else (no overlay, empty
    # overlay, only one of the two set) is unclassified.
    classified_ids = (
        ExpenseDataOverlay.objects.filter(feuser=feuser, category__isnull=False, tags__isnull=False)
        .values_list("expense_id", flat=True)
        .distinct()
    )
    foreign = (
        Expense.objects.filter(pk__in=expense_ids, is_buddies_settlement=False)
        .exclude(owning_feuser=feuser)
        .exclude(pk__in=classified_ids)
        .exclude(type__in=_EXCLUDED_TYPES)
        .count()
    )
    return own + foreign
