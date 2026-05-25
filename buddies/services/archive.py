from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from ..models import BuddyGroupMember, BuddySpending, DummyUser

ARCHIVE_DISPLAY_NAME = "Achim Archive"


class BuddyArchiveService:
    """Manages the per-group and per-user archive dummies (Achim Archive)."""

    @staticmethod
    @transaction.atomic
    def get_or_create_group_archive(group) -> tuple[DummyUser, bool]:
        """Return (archive_dummy, created). Creates BuddyGroupMember if new."""
        existing = DummyUser.objects.filter(owning_group=group, is_archive=True).first()
        if existing:
            return existing, False
        archive = DummyUser.objects.create(
            owning_group=group,
            display_name=ARCHIVE_DISPLAY_NAME,
            is_archive=True,
        )
        BuddyGroupMember.objects.create(group=group, dummy=archive)
        return archive, True

    @staticmethod
    @transaction.atomic
    def get_or_create_personal_archive(feuser) -> tuple[DummyUser, bool]:
        """Return (archive_dummy, created)."""
        existing = DummyUser.objects.filter(owning_feuser=feuser, is_archive=True).first()
        if existing:
            return existing, False
        archive = DummyUser.objects.create(
            owning_feuser=feuser,
            display_name=ARCHIVE_DISPLAY_NAME,
            is_archive=True,
        )
        return archive, True

    @staticmethod
    @transaction.atomic
    def merge_dummy_into_dummy(source: DummyUser, target: DummyUser) -> None:
        """
        Transfer all expense references from source to target.

        BuddySpending rows: if target already participates in the same expense,
        add the share (percentage); otherwise reassign the row. Other participants
        are never touched.

        Upfront-payer expenses: point upfront_payee_dummy to target. If target
        already had an explicit participation row on that same expense, it is
        dropped - the new payer's implicit share absorbs it, mirroring the
        analogous guard in transfer_upfront_payer_to_feuser.

        target need not be the special Achim Archive dummy - this is also used
        to merge one regular offline member directly into another.
        """
        from budget.models import Expense

        buddy_name = source.display_name

        for bs in BuddySpending.objects.filter(participant_dummy=source).select_related("expense"):
            existing = BuddySpending.objects.filter(
                participant_dummy=target, expense_id=bs.expense_id
            ).first()
            if existing:
                existing.share_percent += bs.share_percent
                existing.save(update_fields=["share_percent"])
                bs.delete()
            else:
                bs.participant_dummy = target
                bs.save(update_fields=["participant_dummy"])
            suffix = f"\nOriginal participant was: {buddy_name}"
            expense = bs.expense
            if suffix not in expense.note:
                expense.note = (expense.note + suffix).strip()
                expense.save(update_fields=["note"])

        for expense in Expense.objects.filter(upfront_payee_dummy=source).select_related():
            expense.upfront_payee_dummy = target
            suffix = f"\nOriginally paid by: {buddy_name}"
            if suffix not in expense.note:
                expense.note = (expense.note + suffix).strip()
            expense.save(update_fields=["upfront_payee_dummy", "note"])
            BuddySpending.objects.filter(expense=expense, participant_dummy=target).delete()

    @staticmethod
    @transaction.atomic
    def transfer_dummy_participation_to_feuser(dummy: DummyUser, feuser) -> None:
        """
        Transfer all BuddySpending rows where dummy participates to feuser.

        If feuser already participates in the same expense, the shares are
        summed into that existing row instead of creating a duplicate row for
        the same participant on the same expense.

        If feuser is that expense's own owner (e.g. a project merge target
        who happens to have paid for that particular expense, or a
        self-merge), the row is dropped instead of reassigned - the expense
        owner is never an explicit participant; their implicit share absorbs
        it, same as the equivalent guard in transfer_upfront_payer_to_feuser.
        """
        buddy_name = dummy.display_name

        for bs in BuddySpending.objects.filter(participant_dummy=dummy).select_related("expense"):
            expense = bs.expense
            if expense.owning_feuser_id == feuser.pk:
                bs.delete()
            else:
                existing = BuddySpending.objects.filter(
                    participant_feuser=feuser, expense_id=bs.expense_id
                ).first()
                if existing:
                    existing.share_percent += bs.share_percent
                    existing.save(update_fields=["share_percent"])
                    bs.delete()
                else:
                    bs.participant_dummy = None
                    bs.participant_feuser = feuser
                    bs.save(update_fields=["participant_dummy", "participant_feuser"])
            suffix = f"\nOriginal participant was: {buddy_name}"
            if suffix not in expense.note:
                expense.note = (expense.note + suffix).strip()
                expense.save(update_fields=["note"])

    @staticmethod
    @transaction.atomic
    def transfer_upfront_payer_to_feuser(dummy: DummyUser, feuser) -> None:
        """
        Transfer all expenses where dummy is the upfront payer to feuser becoming
        the real owner.

        feuser may already hold an explicit BuddySpending row on one of these
        expenses (from before they were connected to the payer). The expense
        owner is never an explicit participant, so that stale row is removed;
        its share is absorbed into feuser's implicit owner share.
        """
        from budget.models import Expense
        from .expense import BuddyExpenseService

        for exp in Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True):
            exp.owning_feuser = feuser
            exp.is_dummy = False
            exp.upfront_payee_dummy = None
            BuddyExpenseService.reconcile_categories_tags(exp, feuser)
            exp.save()
            BuddySpending.objects.filter(expense=exp, participant_feuser=feuser).delete()

    @staticmethod
    @transaction.atomic
    def merge_dummy_into_self(dummy: DummyUser, feuser) -> None:
        """
        Merge a dummy directly into its own owner ("self-merge").

        Every BuddySpending row for a personal dummy already lives on an
        expense owned by that same feuser, so transferring participation
        (as transfer_dummy_participation_to_feuser does for a different
        target) would create an explicit owner-as-participant row, which is
        invalid. The row is dropped instead - the owner's implicit share
        silently absorbs it, which is exactly what "no longer a buddy
        expense" means.

        Upfront-payer expenses go through the existing
        transfer_upfront_payer_to_feuser unchanged - feuser becoming the
        real owner of an expense their own dummy used to front is already
        correct there.
        """
        buddy_name = dummy.display_name

        for bs in BuddySpending.objects.filter(participant_dummy=dummy).select_related("expense"):
            expense = bs.expense
            bs.delete()
            suffix = f"\nOriginal participant was: {buddy_name}"
            if suffix not in expense.note:
                expense.note = (expense.note + suffix).strip()
                expense.save(update_fields=["note"])

        BuddyArchiveService.transfer_upfront_payer_to_feuser(dummy, feuser)

    @staticmethod
    def archive_has_expenses(archive: DummyUser) -> bool:
        from budget.models import Expense
        return (
            BuddySpending.objects.filter(participant_dummy=archive).exists()
            or Expense.objects.filter(upfront_payee_dummy=archive).exists()
        )

    @staticmethod
    def get_archive_expense_count(archive: DummyUser) -> int:
        from budget.models import Expense
        participant = (
            BuddySpending.objects.filter(participant_dummy=archive)
            .values("expense")
            .distinct()
            .count()
        )
        payer = Expense.objects.filter(upfront_payee_dummy=archive, is_dummy=True).count()
        return participant + payer

    @staticmethod
    def get_archive_expense_counts_split(archive: DummyUser) -> tuple[int, int]:
        """
        Return (participant_count, payer_count).

        participant_count: expenses where archive is only a participant (BuddySpending rows).
          These expenses survive the wipe; only the split record is removed.
        payer_count: expenses where archive is the upfront payer (is_dummy=True).
          These expenses are fully deleted by wipe_archive.
        """
        from budget.models import Expense
        participant = (
            BuddySpending.objects.filter(participant_dummy=archive)
            .values("expense")
            .distinct()
            .count()
        )
        payer = Expense.objects.filter(upfront_payee_dummy=archive, is_dummy=True).count()
        return participant, payer

    @staticmethod
    def get_group_dummy_balance(dummy: DummyUser, group) -> Decimal:
        """
        Net balance for a group dummy (approved expenses only).
        Positive = dummy is owed by others.
        Negative = dummy owes others.
        """
        from budget.models import Expense

        owed_by = Decimal("0")
        for bs in BuddySpending.objects.filter(
            participant_dummy=dummy,
            expense__project=group,
            expense__buddy_approved=True,
        ).select_related("expense"):
            owed_by += bs.expense.value * bs.share_percent / 100

        owed_to = Decimal("0")
        for exp in Expense.objects.filter(
            upfront_payee_dummy=dummy,
            project=group,
            is_dummy=True,
            buddy_approved=True,
        ).prefetch_related("buddy_spendings"):
            participant_sum = sum(bs.share_percent for bs in exp.buddy_spendings.all())
            owed_to += exp.value * participant_sum / 100

        return owed_to - owed_by

    @staticmethod
    def get_user_impact_in_group_archive(feuser, archive: DummyUser, group) -> Decimal:
        """
        Net financial impact on feuser from all archive expenses in this group.
        Positive = feuser gains when archive is wiped (archive owed feuser).
        Negative = feuser loses when archive is wiped (feuser owed archive).
        """
        owed_by_archive = Decimal("0")
        for bs in BuddySpending.objects.filter(
            participant_dummy=archive,
            expense__owning_feuser=feuser,
            expense__project=group,
            expense__is_dummy=False,
            expense__buddy_approved=True,
        ).select_related("expense"):
            owed_by_archive += bs.expense.value * bs.share_percent / 100

        owed_to_archive = Decimal("0")
        for bs in BuddySpending.objects.filter(
            participant_feuser=feuser,
            expense__upfront_payee_dummy=archive,
            expense__project=group,
            expense__is_dummy=True,
            expense__buddy_approved=True,
        ).select_related("expense"):
            owed_to_archive += bs.expense.value * bs.share_percent / 100

        return owed_by_archive - owed_to_archive

    @staticmethod
    def get_user_impact_in_personal_archive(feuser, archive: DummyUser) -> Decimal:
        """Net financial impact on feuser from personal archive. Uses same logic as get_net_debt."""
        from .query import BuddyQueryService
        return BuddyQueryService.get_net_debt(feuser, buddy_dummy=archive)

    @staticmethod
    @transaction.atomic
    def wipe_archive(archive: DummyUser) -> None:
        """
        Delete all expense references held by archive, then delete the archive itself.

        Participant rows (archive owes someone): the spending row is deleted.
        The expense remains owned by whoever paid it; the payer's implicit share
        increases to absorb Achim's old portion.

        Payer expenses (archive fronted cash): the entire expense is deleted.
        """
        from budget.models import Expense
        BuddySpending.objects.filter(participant_dummy=archive).delete()
        Expense.objects.filter(upfront_payee_dummy=archive, is_dummy=True).delete()
        archive.delete()
