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
    def merge_dummy_into_archive(dummy: DummyUser, archive: DummyUser) -> None:
        """
        Transfer all expense references from dummy to archive.

        BuddySpending rows: if archive already participates in the same expense,
        add the share (percentage); otherwise reassign the row. Other participants
        are never touched.

        Upfront-payer expenses: simply point upfront_payee_dummy to archive.
        """
        from budget.models import Expense

        buddy_name = dummy.display_name

        for bs in BuddySpending.objects.filter(participant_dummy=dummy).select_related("expense"):
            existing = BuddySpending.objects.filter(
                participant_dummy=archive, expense_id=bs.expense_id
            ).first()
            if existing:
                existing.share_percent += bs.share_percent
                existing.save(update_fields=["share_percent"])
                bs.delete()
            else:
                bs.participant_dummy = archive
                bs.save(update_fields=["participant_dummy"])
            suffix = f"\nOriginal participant was: {buddy_name}"
            expense = bs.expense
            if suffix not in expense.note:
                expense.note = (expense.note + suffix).strip()
                expense.save(update_fields=["note"])

        for expense in Expense.objects.filter(upfront_payee_dummy=dummy).select_related():
            expense.upfront_payee_dummy = archive
            suffix = f"\nArchived from: {buddy_name}"
            if suffix not in expense.note:
                expense.note = (expense.note + suffix).strip()
            expense.save(update_fields=["upfront_payee_dummy", "note"])

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
            expense__buddy_group=group,
            expense__buddy_approved=True,
        ).select_related("expense"):
            owed_by += bs.expense.value * bs.share_percent / 100

        owed_to = Decimal("0")
        for exp in Expense.objects.filter(
            upfront_payee_dummy=dummy,
            buddy_group=group,
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
            expense__buddy_group=group,
            expense__is_dummy=False,
            expense__buddy_approved=True,
        ).select_related("expense"):
            owed_by_archive += bs.expense.value * bs.share_percent / 100

        owed_to_archive = Decimal("0")
        for bs in BuddySpending.objects.filter(
            participant_feuser=feuser,
            expense__upfront_payee_dummy=archive,
            expense__buddy_group=group,
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
