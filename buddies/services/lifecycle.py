from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction

from ..models import (
    ProjectMember,
    BuddyGroupMember,  # alias for ProjectMember
    BuddyInvite,
    BuddyLink,
    BuddyOnboardingInvite,
    BuddySpending,
    DummyMergeInvite,
    DummyUser,
)
from ._helpers import _create_link, _display_name
from .email import BuddyEmailService
from .expense import BuddyExpenseService
from .group import BuddyGroupService
from .query import BuddyQueryService


class BuddyLifecycleService:
    """Buddy relationship management: add, invite, kick, merge."""

    @staticmethod
    def add_dummy(feuser, display_name: str) -> DummyUser:
        return DummyUser.objects.create(
            owning_feuser=feuser,
            display_name=display_name.strip(),
        )

    @staticmethod
    @transaction.atomic
    def invite_actual(feuser, email: str):
        """
        Invite an actual user by email as a personal buddy.
        Returns ('link'|'invite'|'onboarding'|'onboarding_no_email'|
                 'already_buddies'|'self'|'registration_disabled', obj).
        """
        from feusers.models import FeUser

        email = email.strip().lower()

        if email == feuser.email.lower():
            return ("self", None)

        if feuser.is_demo:
            return ("demo_restricted", None)

        try:
            invitee = FeUser.objects.get(email__iexact=email, is_active=True)
        except FeUser.DoesNotExist:
            invitee = None

        if invitee and invitee.is_demo:
            return ("invitee_is_demo", None)

        if invitee and BuddyLink.between(feuser, invitee):
            return ("already_buddies", None)

        if settings.DISABLE_EMAILING:
            if invitee:
                link = _create_link(feuser, invitee)
                return ("link", link)
            if not settings.ENABLE_REGISTRATION:
                return ("registration_disabled", None)
            ob = BuddyOnboardingInvite(inviting_feuser=feuser, invitee_email=email)
            ob.save()
            return ("onboarding_no_email", ob)

        if invitee:
            invite = BuddyInvite(inviter=feuser, invitee_email=email)
            invite.save()
            BuddyEmailService.send_buddy_invite(invite)
            return ("invite", invite)

        if not settings.ENABLE_REGISTRATION:
            return ("registration_disabled", None)
        ob = BuddyOnboardingInvite(inviting_feuser=feuser, invitee_email=email)
        ob.save()
        BuddyEmailService.send_onboarding_invite(ob)
        return ("onboarding", ob)

    @staticmethod
    @transaction.atomic
    def accept_invite(token: str, accepting_feuser) -> BuddyLink | None:
        try:
            invite = BuddyInvite.objects.get(token=token)
        except BuddyInvite.DoesNotExist:
            return None

        if not invite.is_valid():
            invite.delete()
            return None

        if invite.invitee_email.lower() != accepting_feuser.email.lower():
            return None

        link = _create_link(invite.inviter, accepting_feuser)
        invite.delete()
        return link

    @staticmethod
    def decline_invite(token: str, declining_feuser) -> bool:
        try:
            invite = BuddyInvite.objects.get(token=token, invitee_email=declining_feuser.email)
        except BuddyInvite.DoesNotExist:
            return False
        invite.delete()
        return True

    @staticmethod
    def revoke_invite(token: str, revoking_feuser) -> bool:
        try:
            invite = BuddyInvite.objects.get(token=token, inviter=revoking_feuser)
        except BuddyInvite.DoesNotExist:
            return False
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def kick_dummy(feuser, dummy: DummyUser, has_debt_warning_accepted: bool = False) -> dict:
        """
        Remove a personal dummy.

        If the dummy is an archive, refuse if it holds expenses
        (returns {'archive_has_expenses': True}); otherwise delete it.

        Otherwise, all expense references are merged into the user's personal
        Achim Archive (created lazily). Returns {'kicked': True,
        'archive_created': bool}.
        """
        from .archive import BuddyArchiveService
        from budget.models import Expense

        if dummy.is_archive:
            if BuddyArchiveService.archive_has_expenses(dummy):
                return {"archive_has_expenses": True}
            dummy.delete()
            return {"kicked": True, "archive_created": False}

        net = BuddyQueryService.get_net_debt(feuser, buddy_dummy=dummy)
        if abs(net) > Decimal("0.05") and not has_debt_warning_accepted:
            return {"debt_warning": net}

        has_expenses = (
            BuddySpending.objects.filter(participant_dummy=dummy).exists()
            or Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True).exists()
        )

        if has_expenses:
            archive, created = BuddyArchiveService.get_or_create_personal_archive(feuser)
            BuddyArchiveService.merge_dummy_into_dummy(dummy, archive)
        else:
            created = False

        # Reset any scheduled expense assignments that reference this dummy before deletion
        from django.db.models import Q
        from budget.models import ScheduledExpense
        from budget.scheduled_assignment import clear_scheduled_assignments
        clear_scheduled_assignments(
            ScheduledExpense.objects.filter(owning_feuser=feuser).filter(
                Q(assign_upfront_dummy=dummy) |
                Q(assign_buddy_mode__in=['single', 'group'],
                  assign_spendings_json__contains=f'"id": {dummy.uid}')
            )
        )

        dummy.delete()
        return {"kicked": True, "archive_created": created}

    @staticmethod
    @transaction.atomic
    def merge_dummy_into_dummy_now(feuser, source: DummyUser, target: DummyUser):
        """
        Immediately merge one personal offline buddy into another. Irreversible.
        Returns 'invalid_dummy' if either dummy is not a personal, non-archive
        dummy, 'already_pending' if source has an outstanding merge request
        (revoke it first), otherwise 'ok'.
        """
        for dummy in (source, target):
            if dummy.owning_group_id is not None or dummy.is_archive:
                return "invalid_dummy"

        from django.utils import timezone
        if DummyMergeInvite.objects.filter(dummy=source, expires_at__gt=timezone.now()).exists():
            return "already_pending"

        from .archive import BuddyArchiveService
        from budget.scheduled_assignment import replace_dummy_in_scheduled

        BuddyArchiveService.merge_dummy_into_dummy(source, target)
        replace_dummy_in_scheduled(feuser, source, target)

        source.delete()
        return "ok"

    @staticmethod
    @transaction.atomic
    def merge_dummy_into_self(feuser, dummy: DummyUser) -> str:
        """
        Merge a personal offline buddy directly into its own owner
        ("self-merge"). Immediate, like merge_dummy_into_dummy_now - there's
        no second party to ask. Returns 'already_pending' if dummy has an
        outstanding merge request (revoke it first), otherwise 'ok'.
        """
        from django.db.models import Q
        from django.utils import timezone

        if DummyMergeInvite.objects.filter(dummy=dummy, expires_at__gt=timezone.now()).exists():
            return "already_pending"

        from .archive import BuddyArchiveService
        from budget.models import ScheduledExpense
        from budget.scheduled_assignment import clear_scheduled_assignments

        BuddyArchiveService.merge_dummy_into_self(dummy, feuser)

        clear_scheduled_assignments(
            ScheduledExpense.objects.filter(owning_feuser=feuser).filter(
                Q(assign_upfront_dummy=dummy) |
                Q(assign_buddy_mode__in=['single', 'group'],
                  assign_spendings_json__contains=f'"id": {dummy.uid}')
            )
        )

        dummy.delete()
        return "ok"

    @staticmethod
    @transaction.atomic
    def kick_actual(feuser, other_feuser, has_debt_warning_accepted: bool = False) -> dict:
        from budget.models import Expense

        net = BuddyQueryService.get_net_debt(feuser, buddy_feuser=other_feuser)
        if abs(net) > Decimal("0.05") and not has_debt_warning_accepted:
            return {"debt_warning": net}

        link = BuddyLink.between(feuser, other_feuser)
        if not link:
            return {"kicked": True}

        feuser_expenses_with_other = Expense.objects.filter(
            owning_feuser=feuser,
            is_dummy=False,
            project__isnull=True,
            buddy_spendings__participant_feuser=other_feuser,
        ).distinct()
        for exp in feuser_expenses_with_other:
            new_dummy = DummyUser.objects.create(
                owning_feuser=other_feuser,
                display_name=_display_name(feuser),
            )
            BuddyExpenseService.clone_expense_for_feuser(exp, other_feuser, new_dummy)
            exp.buddy_spendings.filter(participant_feuser=other_feuser).delete()

        kicker_dummy_for_other = DummyUser.objects.create(
            owning_feuser=other_feuser,
            display_name=_display_name(feuser),
        )
        BuddySpending.objects.filter(
            participant_feuser=feuser,
            expense__owning_feuser=other_feuser,
            expense__project__isnull=True,
        ).update(participant_feuser=None, participant_dummy=kicker_dummy_for_other)

        # Clear feuser's scheduled expense assignments that reference other_feuser
        from django.db.models import Q
        from budget.models import ScheduledExpense
        from budget.scheduled_assignment import clear_scheduled_assignments
        clear_scheduled_assignments(
            ScheduledExpense.objects.filter(owning_feuser=feuser).filter(
                Q(assign_upfront_feuser=other_feuser) |
                Q(assign_buddy_mode__in=['single', 'group'],
                  assign_spendings_json__contains=f'"id": {other_feuser.pk}')
            )
        )

        link.delete()
        BuddyEmailService.send_kicked_notification(
            kicked_feuser=other_feuser,
            kicking_display_name=_display_name(feuser),
        )
        return {"kicked": True}

    @staticmethod
    @transaction.atomic
    def handle_account_deletion(feuser):
        """
        Called before feuser.delete().
        Converts all actual buddy relationships to dummy relationships.
        Also handles group memberships.
        """
        from budget.models import Expense

        for link in BuddyLink.for_user(feuser):
            other = link.other(feuser)

            ghost_dummy = DummyUser.objects.create(
                owning_feuser=other,
                display_name=_display_name(feuser),
            )

            BuddySpending.objects.filter(
                participant_feuser=feuser,
                expense__owning_feuser=other,
                expense__project__isnull=True,
            ).update(participant_feuser=None, participant_dummy=ghost_dummy)

            feuser_exps = Expense.objects.filter(
                owning_feuser=feuser,
                is_dummy=False,
                project__isnull=True,
                buddy_spendings__participant_feuser=other,
            ).distinct()
            for exp in feuser_exps:
                BuddyExpenseService.clone_expense_for_feuser(exp, other, ghost_dummy)

            # Update other's scheduled expenses that reference the deleting feuser
            from budget.scheduled_assignment import replace_feuser_with_dummy_in_scheduled
            replace_feuser_with_dummy_in_scheduled(other, feuser, ghost_dummy)

        BuddyLink.for_user(feuser).delete()

        for membership in BuddyGroupMember.objects.filter(feuser=feuser).select_related("group"):
            group = membership.group

            # If feuser is the only real FeUser in this project, delete the whole project
            other_real_member = (
                BuddyGroupMember.objects
                .filter(group=group, feuser__isnull=False)
                .exclude(feuser=feuser)
                .first()
            )
            if not other_real_member:
                group.delete()
                continue

            if group.admin_feuser_id == feuser.pk:
                other_member = (
                    BuddyGroupMember.objects
                    .filter(group=group, feuser__isnull=False)
                    .exclude(feuser=feuser)
                    .select_related("feuser")
                    .first()
                )
                if other_member:
                    group.admin_feuser = other_member.feuser
                    group.save(update_fields=["admin_feuser"])
                else:
                    BuddyGroupService.dissolve_group(group, feuser)
                    continue

            BuddyGroupService.remove_member(group, group.admin_feuser, membership, notify=False)

    @staticmethod
    @transaction.atomic
    def request_merge_with_feuser(feuser, dummy: DummyUser, target_feuser):
        """
        Ask an already-linked direct buddy to approve merging dummy's expense
        history into their account. Returns ('demo_restricted'|'self'|
        'target_is_demo'|'not_linked'|'already_pending'|'invalid_dummy'|
        'invite', invite_or_None).
        """
        from django.utils import timezone

        if dummy.owning_group_id is not None or dummy.is_archive:
            return ("invalid_dummy", None)

        if feuser.is_demo:
            return ("demo_restricted", None)

        if target_feuser.pk == feuser.pk:
            return ("self", None)

        if target_feuser.is_demo:
            return ("target_is_demo", None)

        if not BuddyQueryService.are_buddies(feuser, target_feuser):
            return ("not_linked", None)

        if DummyMergeInvite.objects.filter(dummy=dummy, expires_at__gt=timezone.now()).exists():
            return ("already_pending", None)

        invite = DummyMergeInvite(
            inviting_feuser=feuser,
            dummy=dummy,
            invited_feuser=target_feuser,
        )
        invite.save()
        BuddyEmailService.send_merge_invite(invite)
        return ("invite", invite)

    @staticmethod
    def revoke_merge_invite(token: str, revoking_feuser) -> bool:
        try:
            invite = DummyMergeInvite.objects.get(token=token, inviting_feuser=revoking_feuser)
        except DummyMergeInvite.DoesNotExist:
            return False
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def accept_merge(token: str, accepting_feuser) -> bool:
        try:
            invite = DummyMergeInvite.objects.select_related(
                "dummy", "inviting_feuser"
            ).get(token=token)
        except DummyMergeInvite.DoesNotExist:
            return False

        if not invite.is_valid():
            invite.delete()
            return False

        if invite.invited_feuser_id != accepting_feuser.pk:
            return False

        dummy = invite.dummy
        inviting_feuser = invite.inviting_feuser

        if dummy.owning_group_id:
            return BuddyGroupService.accept_group_dummy_merge(token, accepting_feuser)

        # Re-check the precondition at accept time, not just request time: up to
        # 7 days may have passed, during which the two could have un-buddied. If
        # so, _create_link below would silently re-establish a connection the
        # user deliberately severed.
        if not BuddyQueryService.are_buddies(inviting_feuser, accepting_feuser):
            return False

        from .archive import BuddyArchiveService
        from budget.scheduled_assignment import replace_dummy_in_scheduled
        BuddyArchiveService.transfer_upfront_payer_to_feuser(dummy, accepting_feuser)
        BuddyArchiveService.transfer_dummy_participation_to_feuser(dummy, accepting_feuser)
        replace_dummy_in_scheduled(inviting_feuser, dummy, accepting_feuser)

        _create_link(inviting_feuser, accepting_feuser)

        dummy.delete()
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def complete_onboarding_invites(new_feuser) -> None:
        from django.utils import timezone

        pending = BuddyOnboardingInvite.objects.filter(
            invitee_email__iexact=new_feuser.email,
            expires_at__gt=timezone.now(),
        ).select_related("inviting_feuser", "group")

        for invite in pending:
            if invite.group_id:
                _create_link(invite.inviting_feuser, new_feuser)
                _, member_created = BuddyGroupMember.objects.get_or_create(group=invite.group, feuser=new_feuser)
                if member_created:
                    from budget.scheduled_assignment import reset_project_assignment_to_equal_shares
                    reset_project_assignment_to_equal_shares(invite.group)

            else:
                _create_link(invite.inviting_feuser, new_feuser)

            invite.delete()

    @staticmethod
    @transaction.atomic
    def approve_expense(expense) -> bool:
        if expense.buddy_approved:
            return False
        expense.buddy_approved = True
        expense.save(update_fields=["buddy_approved"])
        return True

    @staticmethod
    @transaction.atomic
    def reject_expense(expense, rejecting_feuser) -> bool:
        if expense.buddy_approved:
            return False

        if expense.owning_feuser_id == rejecting_feuser.pk:
            participants_to_notify = [
                bs.participant_feuser
                for bs in expense.buddy_spendings.select_related("participant_feuser").all()
                if bs.participant_feuser_id
            ]
            expense.delete()
            for participant in participants_to_notify:
                BuddyEmailService.send_rejection_notification(
                    expense=expense,
                    rejecting_feuser=rejecting_feuser,
                    notifying_feuser=participant,
                    owner_rejected=True,
                )
            return True

        bs_row = expense.buddy_spendings.filter(participant_feuser=rejecting_feuser).first()
        if not bs_row:
            return False

        released_share = bs_row.share_percent
        bs_row.delete()

        remaining = list(expense.buddy_spendings.all())
        if remaining:
            per_participant = released_share / len(remaining)
            for bs in remaining:
                bs.share_percent += per_participant
            BuddySpending.objects.bulk_update(remaining, ["share_percent"])

        expense.buddy_approved = True
        expense.save(update_fields=["buddy_approved"])

        remaining_actual = [
            bs.participant_feuser
            for bs in expense.buddy_spendings.select_related("participant_feuser").all()
            if bs.participant_feuser_id
        ]
        for participant in remaining_actual:
            BuddyEmailService.send_rejection_notification(
                expense=expense,
                rejecting_feuser=rejecting_feuser,
                notifying_feuser=participant,
            )

        return True
