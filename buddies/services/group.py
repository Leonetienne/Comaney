from __future__ import annotations

from django.conf import settings
from django.db import transaction

from ..models import (
    BuddyGroup,
    BuddyGroupInvite,
    BuddyGroupMember,
    BuddyLink,
    BuddyOnboardingInvite,
    BuddySpending,
    DummyMergeInvite,
    DummyUser,
)
from ._helpers import _create_link, _display_name
from .email import BuddyEmailService
from .expense import BuddyExpenseService


class BuddyGroupService:
    """Manages buddy group lifecycle."""

    @staticmethod
    @transaction.atomic
    def create_group(admin_feuser, name: str) -> BuddyGroup:
        name = name.strip()
        group = BuddyGroup.objects.create(name=name, admin_feuser=admin_feuser)
        BuddyGroupMember.objects.create(group=group, feuser=admin_feuser)
        return group

    @staticmethod
    @transaction.atomic
    def invite_member(group, admin_feuser, email: str):
        """
        Invite a user by email to join a group.
        Creates a BuddyLink simultaneously if they are not yet buddies.
        Returns one of:
          ('self', None)
          ('already_member', BuddyGroupMember)
          ('member', BuddyGroupMember) - DISABLE_EMAILING path
          ('invite', BuddyGroupInvite)
          ('onboarding', BuddyOnboardingInvite)
          ('onboarding_no_email', BuddyOnboardingInvite)
          ('registration_disabled', None)
        """
        from feusers.models import FeUser

        email = email.strip().lower()

        if email == admin_feuser.email.lower():
            return ("self", None)

        try:
            invitee = FeUser.objects.get(email__iexact=email, is_active=True)
        except FeUser.DoesNotExist:
            invitee = None

        if invitee:
            existing = BuddyGroupMember.objects.filter(group=group, feuser=invitee).first()
            if existing:
                return ("already_member", existing)

        if settings.DISABLE_EMAILING:
            if invitee:
                if not BuddyLink.between(admin_feuser, invitee):
                    _create_link(admin_feuser, invitee)
                member, _ = BuddyGroupMember.objects.get_or_create(group=group, feuser=invitee)
                return ("member", member)
            if not settings.ENABLE_REGISTRATION:
                return ("registration_disabled", None)
            ob = BuddyOnboardingInvite(
                inviting_feuser=admin_feuser, group=group, invitee_email=email
            )
            ob.save()
            return ("onboarding_no_email", ob)

        if invitee:
            invite = BuddyGroupInvite(
                group=group, inviting_feuser=admin_feuser, invitee_email=email
            )
            invite.save()
            BuddyEmailService.send_group_invite(invite, invitee)
            return ("invite", invite)

        if not settings.ENABLE_REGISTRATION:
            return ("registration_disabled", None)

        ob = BuddyOnboardingInvite(
            inviting_feuser=admin_feuser, group=group, invitee_email=email
        )
        ob.save()
        BuddyEmailService.send_group_onboarding_invite(ob)
        return ("onboarding", ob)

    @staticmethod
    @transaction.atomic
    def accept_group_invite(token: str, accepting_feuser) -> BuddyGroup | None:
        """Accept a BuddyGroupInvite. Returns the group or None if invalid."""
        try:
            invite = BuddyGroupInvite.objects.select_related(
                "group", "inviting_feuser"
            ).get(token=token)
        except BuddyGroupInvite.DoesNotExist:
            return None

        if not invite.is_valid():
            invite.delete()
            return None

        if invite.invitee_email.lower() != accepting_feuser.email.lower():
            return None

        group = invite.group
        inviting_feuser = invite.inviting_feuser

        if not BuddyLink.between(inviting_feuser, accepting_feuser):
            _create_link(inviting_feuser, accepting_feuser)

        BuddyGroupMember.objects.get_or_create(group=group, feuser=accepting_feuser)

        BuddyEmailService.send_group_invite_accepted(invite, _display_name(accepting_feuser))
        invite.delete()
        return group

    @staticmethod
    def decline_group_invite(token: str, declining_feuser) -> bool:
        try:
            invite = BuddyGroupInvite.objects.select_related(
                "inviting_feuser", "group"
            ).get(token=token, invitee_email=declining_feuser.email)
        except BuddyGroupInvite.DoesNotExist:
            return False
        BuddyEmailService.send_group_invite_declined(invite, _display_name(declining_feuser))
        invite.delete()
        return True

    @staticmethod
    def revoke_group_invite(token: str, revoking_feuser) -> bool:
        try:
            invite = BuddyGroupInvite.objects.get(
                token=token, group__admin_feuser=revoking_feuser
            )
        except BuddyGroupInvite.DoesNotExist:
            return False
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def remove_member(group, admin_feuser, target_member: BuddyGroupMember) -> DummyUser:
        """
        Remove a feuser member from the group.
        Replaces them with a group dummy in all historical group expenses.
        Returns the created ghost dummy.
        """
        removed_feuser = target_member.feuser
        ghost_dummy = DummyUser.objects.create(
            owning_group=group,
            display_name=_display_name(removed_feuser),
        )
        BuddyGroupMember.objects.create(group=group, dummy=ghost_dummy)

        BuddySpending.objects.filter(
            participant_feuser=removed_feuser,
            expense__buddy_group=group,
        ).update(participant_feuser=None, participant_dummy=ghost_dummy)

        target_member.delete()
        return ghost_dummy

    @staticmethod
    @transaction.atomic
    def create_group_dummy(group, admin_feuser, display_name: str) -> DummyUser:
        dummy = DummyUser.objects.create(
            owning_group=group,
            display_name=display_name.strip(),
        )
        BuddyGroupMember.objects.create(group=group, dummy=dummy)
        return dummy

    @staticmethod
    @transaction.atomic
    def delete_group_dummy(group, admin_feuser, dummy: DummyUser) -> bool:
        """
        Remove a group dummy.

        If the dummy is the archive, deletion is only permitted when the archive
        holds no expenses (caller must enforce this guard). Returns False.

        Otherwise, all expense references are merged into the group's Achim Archive
        (created lazily). The dummy is then deleted. Returns True if the archive
        was newly created, False if it already existed.
        """
        from budget.models import Expense
        from .archive import BuddyArchiveService

        if dummy.is_archive:
            dummy.delete()
            return False

        has_expenses = (
            BuddySpending.objects.filter(participant_dummy=dummy).exists()
            or Expense.objects.filter(upfront_payee_dummy=dummy).exists()
        )

        if has_expenses:
            archive, created = BuddyArchiveService.get_or_create_group_archive(group)
            BuddyArchiveService.merge_dummy_into_archive(dummy, archive)
        else:
            created = False

        dummy.delete()
        return created

    @staticmethod
    @transaction.atomic
    def send_group_dummy_merge_invite(group, admin_feuser, dummy: DummyUser, target_email: str):
        """
        Invite a real user to take over a group dummy's history.
        Also joins them to the group as a member.
        Returns same tuple format as BuddyLifecycleService.send_merge_invite.
        """
        from feusers.models import FeUser

        target_email = target_email.strip().lower()
        try:
            invited = FeUser.objects.get(email__iexact=target_email, is_active=True)
        except FeUser.DoesNotExist:
            invited = None

        if invited is None:
            if settings.DISABLE_EMAILING:
                if not settings.ENABLE_REGISTRATION:
                    return ("registration_disabled", None)
                ob = BuddyOnboardingInvite(
                    inviting_feuser=admin_feuser,
                    dummy=dummy,
                    group=group,
                    invitee_email=target_email,
                )
                ob.save()
                return ("onboarding_no_email", ob)
            if not settings.ENABLE_REGISTRATION:
                return ("registration_disabled", None)
            ob = BuddyOnboardingInvite(
                inviting_feuser=admin_feuser,
                dummy=dummy,
                group=group,
                invitee_email=target_email,
            )
            ob.save()
            BuddyEmailService.send_group_onboarding_invite(ob)
            return ("onboarding", ob)

        invite = DummyMergeInvite(
            inviting_feuser=admin_feuser,
            dummy=dummy,
            invited_feuser=invited,
        )
        invite.save()
        BuddyEmailService.send_merge_invite(invite)
        return ("invite", invite)

    @staticmethod
    @transaction.atomic
    def accept_group_dummy_merge(token: str, accepting_feuser) -> bool:
        """
        Accept a DummyMergeInvite for a group dummy.
        Transfers the dummy's expense history, adds the user to the group.
        """
        from budget.models import Expense

        try:
            invite = DummyMergeInvite.objects.select_related(
                "dummy__owning_group", "inviting_feuser"
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
        group = dummy.owning_group

        for exp in Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True):
            exp.owning_feuser = accepting_feuser
            exp.is_dummy = False
            exp.upfront_payee_dummy = None
            BuddyExpenseService.reconcile_categories_tags(exp, accepting_feuser)
            exp.save()

        BuddySpending.objects.filter(participant_dummy=dummy).update(
            participant_dummy=None,
            participant_feuser=accepting_feuser,
        )

        if not BuddyLink.between(inviting_feuser, accepting_feuser):
            _create_link(inviting_feuser, accepting_feuser)

        if group:
            dummy_member = BuddyGroupMember.objects.filter(group=group, dummy=dummy).first()
            if dummy_member:
                dummy_member.delete()
            BuddyGroupMember.objects.get_or_create(group=group, feuser=accepting_feuser)

        dummy.delete()
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def transfer_admin(group, current_admin, new_admin_feuser) -> bool:
        """Transfer admin rights to another feuser group member."""
        if not BuddyGroupMember.objects.filter(group=group, feuser=new_admin_feuser).exists():
            return False
        group.admin_feuser = new_admin_feuser
        group.save(update_fields=["admin_feuser"])
        return True

    @staticmethod
    @transaction.atomic
    def dissolve_group(group, admin_feuser) -> None:
        """
        Dissolve a group. Regular group dummies are transferred to the admin as
        personal dummies. The group's Achim Archive (if any) is merged into the
        admin's personal Achim Archive so history is preserved. Group expenses
        lose their group context (buddy_group becomes NULL via FK SET_NULL).
        """
        from .archive import BuddyArchiveService

        group_archive = DummyUser.objects.filter(owning_group=group, is_archive=True).first()
        if group_archive:
            if BuddyArchiveService.archive_has_expenses(group_archive):
                personal_archive, _ = BuddyArchiveService.get_or_create_personal_archive(
                    admin_feuser
                )
                BuddyArchiveService.merge_dummy_into_archive(group_archive, personal_archive)
            group_archive.delete()

        DummyUser.objects.filter(owning_group=group, is_archive=False).update(
            owning_group=None,
            owning_feuser=admin_feuser,
        )
        group.delete()
