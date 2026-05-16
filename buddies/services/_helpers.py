from __future__ import annotations

from ..models import BuddyLink


def _display_name(feuser) -> str:
    name = f"{feuser.first_name} {feuser.last_name}".strip()
    return name or feuser.email


def _create_link(feuser_a, feuser_b) -> BuddyLink:
    lo, hi = sorted([feuser_a, feuser_b], key=lambda u: u.pk)
    link, _ = BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)
    return link


def _clone_expense_object(source, target_feuser):
    """Return an unsaved Expense copy for target_feuser (no M2M yet)."""
    from budget.models import Expense

    clone = Expense(
        owning_feuser=target_feuser,
        title=source.title,
        payee=source.payee,
        note=source.note,
        type=source.type,
        value=source.value,
        date_due=source.date_due,
        settled=source.settled,
        auto_settle_on_due_date=source.auto_settle_on_due_date,
        notify=source.notify,
        category=source.category,
    )
    if clone.category_id:
        from budget.models import Category
        try:
            clone.category = Category.objects.get(
                owning_feuser=target_feuser,
                title=source.category.title,
            )
        except Category.DoesNotExist:
            clone.category = None

    from budget.models import Tag
    clone._reconciled_tags = []
    for tag in source.tags.all():
        try:
            matched = Tag.objects.get(owning_feuser=target_feuser, title=tag.title)
            clone._reconciled_tags.append(matched)
        except Tag.DoesNotExist:
            pass

    return clone
