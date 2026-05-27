from datetime import date
from decimal import Decimal
from typing import Optional

from feusers.models import FeUser

from .models import Category, Expense, ScheduledExpense, Tag, TransactionType


def create_expense(
    *,
    owning_feuser: FeUser,
    title: str,
    type: TransactionType,
    value: Decimal,
    payee: str = "",
    note: str = "",
    category: Optional[Category] = None,
    tags: Optional[list[Tag]] = None,
    date_due: Optional[date] = None,
    settled: bool = True,
    auto_settle_on_due_date: bool = False,
    notify: bool = True,
    source_scheduled: Optional[ScheduledExpense] = None,
    scheduled_occurrence_date: Optional[date] = None,
    is_dummy: bool = False,
    is_buddies_settlement: bool = False,
    buddy_approved: bool = True,
    upfront_payee_dummy=None,
    project=None,
    buddy_group=None,  # legacy alias for project
    buddy_spendings: Optional[list[dict]] = None,
) -> Expense:
    is_buddy_expense = bool(project or buddy_group or buddy_spendings or is_dummy)
    if is_buddy_expense and type != TransactionType.EXPENSE:
        raise ValueError("Buddy and project expenses must be type=EXPENSE.")
    expense = Expense.objects.create(
        owning_feuser=owning_feuser,
        title=title,
        type=type,
        value=value,
        payee=payee,
        note=note,
        category=category,
        date_due=date_due,
        settled=settled,
        auto_settle_on_due_date=auto_settle_on_due_date,
        notify=notify,
        source_scheduled=source_scheduled,
        scheduled_occurrence_date=scheduled_occurrence_date,
        is_dummy=is_dummy,
        is_buddies_settlement=is_buddies_settlement,
        buddy_approved=buddy_approved,
        upfront_payee_dummy=upfront_payee_dummy,
        project=project or buddy_group,
    )
    if tags:
        expense.tags.set(tags)
    if buddy_spendings:
        from buddies.services import BuddyExpenseService
        BuddyExpenseService.set_buddy_spendings(expense, buddy_spendings)
    return expense
