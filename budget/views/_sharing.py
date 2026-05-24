"""
Shared queryset helpers for personal/shared (buddy) mode.
Used by both the dashboard cards API and the REST expenses API.
"""
from decimal import Decimal

from django.db.models import (
    Case, DecimalField, Exists, ExpressionWrapper, F, OuterRef, Q, Subquery,
    Sum, Value, When,
)

from ..models import Expense


def has_buddy_or_multiuser_project(feuser) -> bool:
    """True if feuser has at least one buddy or is in a non-solo project."""
    from buddies.models import BuddyLink, ProjectMember
    if BuddyLink.for_user(feuser).exists():
        return True
    memberships = ProjectMember.objects.filter(feuser=feuser).values_list('group_id', flat=True)
    if not memberships.exists():
        return False
    has_other_feuser = ProjectMember.objects.filter(
        group_id__in=memberships,
        feuser__isnull=False,
    ).exclude(feuser=feuser).exists()
    if has_other_feuser:
        return True
    return ProjectMember.objects.filter(
        group_id__in=memberships,
        dummy__isnull=False,
    ).exists()


def build_shared_qs(feuser, start, end):
    """
    Build the buddy-mode queryset with effective_value annotation.

    Includes:
    - Own expenses (proportional if shared, full if personal/solo)
    - Foreign expenses where feuser is a BuddySpending participant
    Excludes settlement expenses.
    """
    from buddies.models import BuddySpending

    my_share_subq = Subquery(
        BuddySpending.objects.filter(
            expense=OuterRef('pk'),
            participant_feuser=feuser,
        ).values('share_percent')[:1]
    )
    has_any_subq = Exists(
        BuddySpending.objects.filter(expense=OuterRef('pk'))
    )
    # Sum of all participant share_percents — the owner's implied share is (100 - this).
    total_shared_pct_subq = Subquery(
        BuddySpending.objects.filter(
            expense=OuterRef('pk'),
        ).values('expense_id').annotate(
            total=Sum('share_percent'),
        ).values('total')[:1],
        output_field=DecimalField(),
    )

    base_filter = (
        (Q(owning_feuser=feuser) | Q(buddy_spendings__participant_feuser=feuser))
        & Q(deactivated=False, is_buddies_settlement=False)
    )
    if start is not None and end is not None:
        base_filter &= Q(date_due__gte=start, date_due__lte=end)

    return (
        Expense.objects
        .filter(base_filter)
        .distinct()
        .annotate(_my_share=my_share_subq, _has_any=has_any_subq, _total_shared_pct=total_shared_pct_subq)
        .annotate(
            effective_value=Case(
                # Own expense, no BuddySpending rows: full value
                When(owning_feuser=feuser, _has_any=False, then=F('value')),
                # Own expense, spendings exist but owner is not a participant:
                # owner's implied share = 100% - sum(all participant shares)
                When(owning_feuser=feuser, _my_share__isnull=True,
                     then=ExpressionWrapper(
                         F('value') * (Value(Decimal('100')) - F('_total_shared_pct')) / Value(Decimal('100')),
                         output_field=DecimalField())),
                # Own expense with own participant entry (defensive): proportional
                When(owning_feuser=feuser, _my_share__isnull=False,
                     then=ExpressionWrapper(
                         F('value') * F('_my_share') / Value(100),
                         output_field=DecimalField())),
                # Foreign expense where I'm a participant: proportional
                default=ExpressionWrapper(
                    F('value') * F('_my_share') / Value(100),
                    output_field=DecimalField()),
                output_field=DecimalField(),
            )
        )
    )
