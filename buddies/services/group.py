from __future__ import annotations

from django.conf import settings
from django.db import transaction

from ..models import (
    Project,
    ProjectInvite,
    ProjectMember,
    BuddyGroup,  # alias for Project
    BuddyGroupInvite,  # alias for ProjectInvite
    BuddyGroupMember,  # alias for ProjectMember
    BuddyLink,
    BuddyOnboardingInvite,
    BuddySpending,
    DummyMergeInvite,
    DummyUser,
)
from ._helpers import _create_link, _display_name
from .email import BuddyEmailService


class ProjectService:
    """Manages project lifecycle."""

    @staticmethod
    @transaction.atomic
    def create_group(admin_feuser, name: str, description: str = "") -> Project:
        name = name.strip()
        group = Project.objects.create(name=name, admin_feuser=admin_feuser, description=description.strip())
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

        if admin_feuser.is_demo:
            return ("demo_restricted", None)

        try:
            invitee = FeUser.objects.get(email__iexact=email, is_active=True)
        except FeUser.DoesNotExist:
            invitee = None

        if invitee and invitee.is_demo:
            return ("invitee_is_demo", None)

        if invitee:
            existing = BuddyGroupMember.objects.filter(group=group, feuser=invitee).first()
            if existing:
                return ("already_member", existing)

        if settings.DISABLE_EMAILING:
            if invitee:
                if not BuddyLink.between(admin_feuser, invitee):
                    _create_link(admin_feuser, invitee)
                member, created = BuddyGroupMember.objects.get_or_create(group=group, feuser=invitee)
                if created:
                    from budget.scheduled_assignment import reset_project_assignment_to_equal_shares
                    reset_project_assignment_to_equal_shares(group)
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
    def accept_group_invite(token: str, accepting_feuser) -> Project | None:
        """Accept a ProjectInvite. Returns the project or None if invalid."""
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
        group.update_lastmod()

        # Roster changed: reset equal-share spendings on scheduled expenses for this project
        from budget.scheduled_assignment import reset_project_assignment_to_equal_shares
        reset_project_assignment_to_equal_shares(group)

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
    def remove_member(group, admin_feuser, target_member: BuddyGroupMember, *, notify: bool = True) -> DummyUser:
        """
        Remove a feuser member from the group.
        Replaces them with a group dummy in all historical group expenses.
        Returns the created ghost dummy.
        notify=False suppresses the removal email (voluntary leave, account deletion).
        """
        removed_feuser = target_member.feuser
        ghost_dummy = DummyUser.objects.create(
            owning_group=group,
            display_name=_display_name(removed_feuser),
        )

        BuddySpending.objects.filter(
            participant_feuser=removed_feuser,
            expense__project=group,
        ).update(participant_feuser=None, participant_dummy=ghost_dummy)

        target_member.delete()
        group.update_lastmod()

        # Reset equal shares for remaining members' scheduled expenses.
        # Ghost dummy is not yet in BuddyGroupMember, so the roster seen here
        # is exactly the real members who remain — equal shares are computed correctly.
        from budget.models import ScheduledExpense
        from budget.scheduled_assignment import (
            reset_project_assignment_to_equal_shares,
            clear_scheduled_assignments,
        )
        reset_project_assignment_to_equal_shares(group)
        # The removed user is no longer part of the group; clear their assignment entirely.
        clear_scheduled_assignments(ScheduledExpense.objects.filter(
            assign_project=group, owning_feuser=removed_feuser
        ))

        # Add ghost dummy to the roster after the scheduled-expense reset so it
        # doesn't skew the equal-shares calculation above.
        BuddyGroupMember.objects.create(group=group, dummy=ghost_dummy)

        if notify:
            BuddyEmailService.send_group_removed_notification(
                removed_feuser=removed_feuser,
                admin_feuser=admin_feuser,
                group=group,
            )

        return ghost_dummy

    @staticmethod
    @transaction.atomic
    def create_group_dummy(group, admin_feuser, display_name: str) -> DummyUser:
        dummy = DummyUser.objects.create(
            owning_group=group,
            display_name=display_name.strip(),
        )
        BuddyGroupMember.objects.create(group=group, dummy=dummy)
        group.update_lastmod()
        # Roster changed: reset equal-share spendings on scheduled expenses for this project
        from budget.scheduled_assignment import reset_project_assignment_to_equal_shares
        reset_project_assignment_to_equal_shares(group)
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
            BuddyArchiveService.merge_dummy_into_dummy(dummy, archive)
        else:
            created = False

        # Clear all scheduled assignments for this project — roster is now stale
        from budget.models import ScheduledExpense
        from budget.scheduled_assignment import clear_scheduled_assignments
        clear_scheduled_assignments(ScheduledExpense.objects.filter(assign_project=group))

        dummy.delete()
        return created

    @staticmethod
    @transaction.atomic
    def merge_group_dummy_into_dummy_now(group, source: DummyUser, target: DummyUser):
        """
        Immediately merge one offline project member into another. Irreversible.
        Returns 'invalid_dummy' if either dummy does not belong to this group
        or is the archive, 'already_pending' if source has an outstanding
        merge request (revoke it first), otherwise 'ok'.
        """
        for dummy in (source, target):
            if dummy.owning_group_id != group.pk or dummy.is_archive:
                return "invalid_dummy"

        from django.utils import timezone
        if DummyMergeInvite.objects.filter(dummy=source, expires_at__gt=timezone.now()).exists():
            return "already_pending"

        from .archive import BuddyArchiveService

        BuddyArchiveService.merge_dummy_into_dummy(source, target)
        source.delete()

        # Roster changed (source member gone): reset scheduled spendings, same as
        # any other project-membership change.
        from budget.scheduled_assignment import reset_project_assignment_to_equal_shares
        reset_project_assignment_to_equal_shares(group)
        return "ok"

    @staticmethod
    @transaction.atomic
    def merge_group_dummy_into_self(group, admin_feuser, dummy: DummyUser) -> str:
        """
        Merge a project offline member directly into the admin performing
        the merge ("self-merge"). Immediate, like
        merge_group_dummy_into_dummy_now - there's no second party to ask.
        Otherwise reuses the exact same transfer primitives as accepting a
        normal merge-into-member request: per merge-spec.md, project
        self-merge behaves like any other merge. Returns 'already_pending'
        if dummy has an outstanding merge request, otherwise 'ok'.
        """
        from django.utils import timezone

        if DummyMergeInvite.objects.filter(dummy=dummy, expires_at__gt=timezone.now()).exists():
            return "already_pending"

        from .archive import BuddyArchiveService

        BuddyArchiveService.transfer_upfront_payer_to_feuser(dummy, admin_feuser)
        BuddyArchiveService.transfer_dummy_participation_to_feuser(dummy, admin_feuser)

        dummy_member = BuddyGroupMember.objects.filter(group=group, dummy=dummy).first()
        if dummy_member:
            dummy_member.delete()
        dummy.delete()

        # Roster changed (dummy gone): reset scheduled spendings, same as any
        # other project-membership change.
        from budget.scheduled_assignment import reset_project_assignment_to_equal_shares
        reset_project_assignment_to_equal_shares(group)
        return "ok"

    @staticmethod
    @transaction.atomic
    def request_group_merge_with_feuser(admin_feuser, group, dummy: DummyUser, target_feuser):
        """
        Ask an existing project member to approve merging a group dummy's
        history into their account. Returns ('demo_restricted'|'self'|
        'target_is_demo'|'not_member'|'already_pending'|'invalid_dummy'|
        'invite', invite_or_None).
        """
        from django.utils import timezone

        if dummy.owning_group_id != group.pk or dummy.is_archive:
            return ("invalid_dummy", None)

        if admin_feuser.is_demo:
            return ("demo_restricted", None)

        if target_feuser.pk == admin_feuser.pk:
            return ("self", None)

        if target_feuser.is_demo:
            return ("target_is_demo", None)

        if not BuddyGroupMember.objects.filter(group=group, feuser=target_feuser).exists():
            return ("not_member", None)

        if DummyMergeInvite.objects.filter(dummy=dummy, expires_at__gt=timezone.now()).exists():
            return ("already_pending", None)

        invite = DummyMergeInvite(
            inviting_feuser=admin_feuser,
            dummy=dummy,
            invited_feuser=target_feuser,
        )
        invite.save()
        BuddyEmailService.send_merge_invite(invite)
        return ("invite", invite)

    @staticmethod
    @transaction.atomic
    def accept_group_dummy_merge(token: str, accepting_feuser) -> bool:
        """
        Accept a DummyMergeInvite for a group dummy.
        Transfers the dummy's expense history. accepting_feuser is already a
        project member by construction (merge targets must already be a
        member), so this never touches BuddyLink - merging an offline record
        within a shared project must not create an unrelated personal buddy
        connection between the admin and the member.

        Re-checks that precondition (still a member, project not archived) at
        accept time rather than trusting it from request time: up to 7 days
        may have passed, during which the member could have left/been removed
        or the project could have been archived. If either no longer holds,
        accepting fails cleanly instead of re-adding a member who left or
        mutating an archived project.
        """
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
        group = dummy.owning_group

        if group and group.archived:
            return False

        if group and not BuddyGroupMember.objects.filter(group=group, feuser=accepting_feuser).exists():
            return False

        from .archive import BuddyArchiveService
        BuddyArchiveService.transfer_upfront_payer_to_feuser(dummy, accepting_feuser)
        BuddyArchiveService.transfer_dummy_participation_to_feuser(dummy, accepting_feuser)

        if group:
            dummy_member = BuddyGroupMember.objects.filter(group=group, dummy=dummy).first()
            if dummy_member:
                dummy_member.delete()
            BuddyGroupMember.objects.get_or_create(group=group, feuser=accepting_feuser)
            # Roster changed (dummy became real feuser): reset scheduled spendings
            from budget.scheduled_assignment import reset_project_assignment_to_equal_shares
            reset_project_assignment_to_equal_shares(group)

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
                BuddyArchiveService.merge_dummy_into_dummy(group_archive, personal_archive)
            group_archive.delete()

        DummyUser.objects.filter(owning_group=group, is_archive=False).update(
            owning_group=None,
            owning_feuser=admin_feuser,
        )

        # Clear scheduled expense assignments referencing this project before deletion
        from budget.models import ScheduledExpense
        from budget.scheduled_assignment import clear_scheduled_assignments
        clear_scheduled_assignments(ScheduledExpense.objects.filter(assign_project=group))

        group.delete()


BuddyGroupService = ProjectService
