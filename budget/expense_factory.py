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
    is_dummy: bool = False,
    buddy_approved: bool = True,
    upfront_payee_dummy=None,
    buddy_spendings: Optional[list[dict]] = None,
) -> Expense:
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
        is_dummy=is_dummy,
        buddy_approved=buddy_approved,
        upfront_payee_dummy=upfront_payee_dummy,
    )
    if tags:
        expense.tags.set(tags)
    if buddy_spendings:
        from buddies.services import BuddyExpenseService
        BuddyExpenseService.set_buddy_spendings(expense, buddy_spendings)
    return expense
