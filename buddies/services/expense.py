from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from ..models import BuddySpending, DummyUser
from ._helpers import _clone_expense_object


class BuddyExpenseService:
    """Handles expense-level buddy operations."""

    @staticmethod
    def set_buddy_spendings(expense, participants: list[dict]):
        """
        Replace all BuddySpending rows for an expense.
        participants: [{'type': 'feuser'|'dummy', 'id': int, 'share_percent': Decimal}, ...]
        The expense owner must NOT appear in participants for non-group expenses.
        """
        expense.buddy_spendings.all().delete()
        rows = []
        for p in participants:
            bs = BuddySpending(expense=expense, share_percent=Decimal(str(p["share_percent"])))
            if p["type"] == "feuser":
                bs.participant_feuser_id = int(p["id"])
            else:
                bs.participant_dummy_id = int(p["id"])
            rows.append(bs)
        BuddySpending.objects.bulk_create(rows)

    @staticmethod
    def reconcile_categories_tags(expense, target_feuser):
        """
        Match expense's category and tags to target_feuser's sets by title.
        Mutates expense in-place; caller must save.
        """
        from budget.models import Category, Tag

        if expense.category_id:
            try:
                matched = Category.objects.get(
                    owning_feuser=target_feuser,
                    title=expense.category.title,
                )
                expense.category = matched
            except Category.DoesNotExist:
                expense.category = None

        current_tags = list(expense.tags.all())
        matched_tags = []
        for tag in current_tags:
            try:
                matched = Tag.objects.get(owning_feuser=target_feuser, title=tag.title)
                matched_tags.append(matched)
            except Tag.DoesNotExist:
                pass
        expense.tags.set(matched_tags)

    @staticmethod
    @transaction.atomic
    def clone_expense_for_feuser(source_expense, target_feuser, dummy_payer: DummyUser):
        """
        Clone source_expense for target_feuser.
        Result: owning_feuser=target_feuser, is_dummy=True, upfront_payee_dummy=dummy_payer.
        """
        clone = _clone_expense_object(source_expense, target_feuser)
        clone.is_dummy = True
        clone.upfront_payee_dummy = dummy_payer
        clone.buddy_approved = True
        clone.save()
        clone.tags.set(list(clone._reconciled_tags) if hasattr(clone, "_reconciled_tags") else [])

        for bs in source_expense.buddy_spendings.all():
            if bs.participant_feuser_id == target_feuser.pk:
                continue
            BuddySpending.objects.create(
                expense=clone,
                participant_feuser=bs.participant_feuser,
                participant_dummy=bs.participant_dummy,
                share_percent=bs.share_percent,
            )

        return clone

    @staticmethod
    @transaction.atomic
    def change_upfront_payer(expense, new_payer_feuser=None, new_payer_dummy=None):
        """
        Change who is the upfront payer for an existing buddy expense.
        Adjusts BuddySpending rows to maintain share percentages.
        Returns the (possibly mutated) expense.
        """
        old_owner = expense.owning_feuser
        old_dummy_payer = expense.upfront_payee_dummy

        if new_payer_feuser is not None and new_payer_feuser != old_owner:
            new_payer_bs = expense.buddy_spendings.filter(participant_feuser=new_payer_feuser).first()
            participant_sum = sum(bs.share_percent for bs in expense.buddy_spendings.all())
            old_owner_share = Decimal("100") - participant_sum
            if new_payer_bs:
                new_payer_bs.delete()

            if old_owner_dummy := old_dummy_payer:
                BuddySpending.objects.create(
                    expense=expense,
                    participant_dummy=old_owner_dummy,
                    share_percent=old_owner_share,
                )
            else:
                BuddySpending.objects.create(
                    expense=expense,
                    participant_feuser=old_owner,
                    share_percent=old_owner_share,
                )

            expense.owning_feuser = new_payer_feuser
            expense.is_dummy = False
            expense.upfront_payee_dummy = None
            expense.buddy_approved = False
            BuddyExpenseService.reconcile_categories_tags(expense, new_payer_feuser)
            expense.save()

        elif new_payer_dummy is not None and new_payer_dummy != old_dummy_payer:
            dummy_bs = expense.buddy_spendings.filter(participant_dummy=new_payer_dummy).first()
            participant_sum = sum(bs.share_percent for bs in expense.buddy_spendings.all())
            old_payer_share = Decimal("100") - participant_sum
            if dummy_bs:
                dummy_bs.delete()

            if old_dummy_payer:
                BuddySpending.objects.create(
                    expense=expense,
                    participant_dummy=old_dummy_payer,
                    share_percent=old_payer_share,
                )
            else:
                BuddySpending.objects.create(
                    expense=expense,
                    participant_feuser=expense.owning_feuser,
                    share_percent=old_payer_share,
                )

            expense.is_dummy = True
            expense.upfront_payee_dummy = new_payer_dummy
            expense.buddy_approved = True
            expense.save()

        return expense
