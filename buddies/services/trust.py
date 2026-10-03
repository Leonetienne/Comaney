from __future__ import annotations

from typing import NamedTuple

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import BuddyLink, BuddySpending, ProjectInvite
from .email import BuddyEmailService
from .group import ProjectService
from .lifecycle import BuddyLifecycleService


class AutoAcceptResult(NamedTuple):
    """What turning the trust on accepted retroactively."""
    entries: int   # expenses/settlements/participant indicators
    projects: int  # project invitations joined


class BuddyTrustService:
    """
    Buddy auto-accept trust: a feuser (the "truster") can opt to automatically
    accept everything a specific direct buddy (the "actor") records for them,
    instead of confirming it by hand. Stored per direction on BuddyLink, so it
    only exists between direct buddies and vanishes with the link.

    What gets accepted, for an expense whose `initiated_by_feuser` is the actor:
    - "Did you pay for this?": a pending non-settlement expense owned by the truster.
    - Settlement receipt: a pending settlement with the truster as creditor.
    - Participant approval indicator: the truster's neutral BuddySpending row.
    Plus project invitations the actor (as project admin) sends the truster.

    Expenses in archived projects are never touched, and archived projects
    are never joined.
    """

    @staticmethod
    def trusts(truster, actor) -> bool:
        """True when `truster` auto-accepts entries recorded by `actor`."""
        if truster is None or actor is None or truster.pk == actor.pk:
            return False
        link = BuddyLink.between(truster, actor)
        return bool(link and link.auto_accepts(truster))

    @staticmethod
    def record_action(expense, actor, notify: bool = True):
        """
        Call after `actor` created an expense/settlement or changed it in a way
        that needs someone else's confirmation again (new payer, reset approvals,
        edited pending settlement). Stamps the actor as initiator, then
        auto-accepts on behalf of every involved feuser who trusts them.

        Mutates `expense` in place, so callers check `expense.buddy_approved`
        afterwards to decide whether the regular confirmation request is still
        needed. With `notify`, each truster gets an info-only email instead.
        """
        if expense.initiated_by_feuser_id != actor.pk:
            expense.initiated_by_feuser = actor
            expense.save(update_fields=["initiated_by_feuser"])

        candidates = {}
        if expense.owning_feuser_id and not expense.is_dummy:
            candidates[expense.owning_feuser_id] = expense.owning_feuser
        for bs in expense.buddy_spendings.select_related("participant_feuser").filter(
            participant_feuser__isnull=False
        ):
            candidates[bs.participant_feuser_id] = bs.participant_feuser

        for truster in candidates.values():
            if BuddyTrustService.trusts(truster, actor):
                BuddyTrustService._accept_for(expense, truster, actor, notify)

    @staticmethod
    @transaction.atomic
    def _accept_for(expense, truster, actor, notify: bool) -> bool:
        """Accept everything on `expense` that waits on `truster`. Returns True if anything changed."""
        if expense.project_id and expense.project.archived:
            return False
        changed = False

        if not expense.buddy_approved:
            if expense.is_buddies_settlement:
                is_creditor = (
                    expense.owning_feuser_id != truster.pk
                    and expense.buddy_spendings.filter(participant_feuser=truster).exists()
                )
                if is_creditor and BuddyLifecycleService.confirm_settlement(expense, truster):
                    changed = True
                    if notify:
                        BuddyEmailService.send_settlement_auto_accepted(expense, actor, truster)
            elif expense.owning_feuser_id == truster.pk and not expense.is_dummy:
                if BuddyLifecycleService.approve_expense(expense):
                    changed = True
                    if notify:
                        BuddyEmailService.send_expense_auto_accepted(expense, actor)

        if not expense.is_buddies_settlement:
            now = timezone.now()
            updated = BuddySpending.objects.filter(
                expense=expense,
                participant_feuser=truster,
                approval_state=BuddySpending.APPROVAL_NEUTRAL,
            ).update(
                approval_state=BuddySpending.APPROVAL_APPROVED,
                consent_set_at=now,
                last_mod=now,
            )
            changed = changed or bool(updated)

        if changed and expense.project_id:
            expense.project.update_lastmod()
        return changed

    @staticmethod
    def accept_project_invite(invite, invitee, notify: bool = True):
        """
        Join `invitee` into the invite's project on their behalf, the same way a
        manual accept does (ProjectService.join_via_invite), minus the "joined
        your project" email to the inviter, who sees the new member right away.
        Returns the project, or None for an expired/archived invite.
        """
        if not invite.is_valid() or invite.group.archived:
            return None
        inviter = invite.inviting_feuser
        project = ProjectService.join_via_invite(invite, invitee, notify_inviter=False)
        if notify:
            BuddyEmailService.send_project_invite_auto_accepted(project, inviter, invitee)
        return project

    @staticmethod
    def pending_invites_from(truster, actor):
        """Open, unexpired invitations from `actor` to `truster` into non-archived projects."""
        return (
            ProjectInvite.objects
            .filter(inviting_feuser=actor, invitee_email__iexact=truster.email,
                    group__archived=False, expires_at__gt=timezone.now())
            .select_related("group", "inviting_feuser")
        )

    @staticmethod
    def pending_from(truster, actor):
        """
        Expenses recorded by `actor` that currently wait on `truster` and would
        be accepted by turning the trust on (archived projects excluded).
        """
        from budget.models import Expense

        waiting = (
            Q(owning_feuser=truster, buddy_approved=False,
              is_buddies_settlement=False, is_dummy=False)
            | Q(is_buddies_settlement=True, buddy_approved=False,
                buddy_spendings__participant_feuser=truster)
            | Q(is_buddies_settlement=False,
                buddy_spendings__participant_feuser=truster,
                buddy_spendings__approval_state=BuddySpending.APPROVAL_NEUTRAL)
        )
        return (
            Expense.objects
            .filter(initiated_by_feuser=actor)
            .filter(Q(project__isnull=True) | Q(project__archived=False))
            .filter(waiting)
            .select_related("project", "owning_feuser", "upfront_payee_dummy")
            .distinct()
        )

    @staticmethod
    @transaction.atomic
    def set_auto_accept(truster, other, enabled: bool) -> AutoAcceptResult:
        """
        Turn `truster`'s auto-accept of entries from `other` on or off.
        Turning it on also accepts every pending entry `other` already recorded
        (see pending_from) and joins every open project invitation from them
        (see pending_invites_from), silently: the truster just chose this
        themselves. Returns what was accepted retroactively.
        Raises BuddyLink.DoesNotExist if the two are not direct buddies.
        """
        link = BuddyLink.between(truster, other)
        if link is None:
            raise BuddyLink.DoesNotExist
        link.set_auto_accepts(truster, enabled)
        if not enabled:
            return AutoAcceptResult(0, 0)
        entries = sum(
            1 for expense in BuddyTrustService.pending_from(truster, other)
            if BuddyTrustService._accept_for(expense, truster, other, notify=False)
        )
        projects = sum(
            1 for invite in BuddyTrustService.pending_invites_from(truster, other)
            if BuddyTrustService.accept_project_invite(invite, truster, notify=False)
        )
        return AutoAcceptResult(entries, projects)
