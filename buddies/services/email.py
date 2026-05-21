from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from ..models import BuddyInvite, BuddyGroupInvite, BuddyOnboardingInvite, DummyMergeInvite
from ._helpers import _display_name


_CLASS_FIELD = {
    "expense_participation": "notify_expense_participation",
    "expense_assignments":   "notify_expense_assignments",
    "participant_decisions":  "notify_participant_decisions",
    "settlements":            "notify_settlements",
    "group_activity":         "notify_group_activity",
}


class BuddyEmailService:
    """All buddy-related email sending. Respects DISABLE_EMAILING and email_notifications."""

    @staticmethod
    def _send(
        subject: str,
        template: str,
        ctx: dict,
        recipient_email: str,
        respect_prefs: bool = True,
        notification_class: str | None = None,
    ):
        if settings.DISABLE_EMAILING:
            return False

        if respect_prefs:
            feuser = ctx.get("feuser_recipient")
            if feuser:
                if not feuser.email_notifications:
                    return False
                field = _CLASS_FIELD.get(notification_class or "")
                if field and not getattr(feuser, field, True):
                    return False

        html = render_to_string(template, {**ctx, "site_url": getattr(settings, "SITE_URL", "")})
        try:
            send_mail(
                subject=subject,
                message="",
                html_message=html,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
                recipient_list=[recipient_email],
            )
            return True
        except Exception:
            return False

    @staticmethod
    def send_buddy_invite(invite: BuddyInvite):
        from feusers.models import FeUser
        site_url = getattr(settings, "SITE_URL", "")
        invite_url = f"{site_url}/buddies/invite/{invite.token}/"
        try:
            invitee_feuser = FeUser.objects.get(email=invite.invitee_email)
        except FeUser.DoesNotExist:
            invitee_feuser = None
        BuddyEmailService._send(
            subject=f"{_display_name(invite.inviter)} invited you to be spending buddies on Comaney",
            template="emails/buddy_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviter),
                "invite_url": invite_url,
                "feuser_recipient": invitee_feuser,
            },
            recipient_email=invite.invitee_email,
            respect_prefs=invitee_feuser is not None,
            notification_class="group_activity",
        )

    @staticmethod
    def send_group_invite(invite: BuddyGroupInvite, invitee):
        site_url = getattr(settings, "SITE_URL", "")
        invite_url = f"{site_url}/projects/project-invite/{invite.token}/"
        BuddyEmailService._send(
            subject=f"{_display_name(invite.inviting_feuser)} invited you to join the group \"{invite.group.name}\" on Comaney",
            template="emails/buddy_group_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviting_feuser),
                "group_name": invite.group.name,
                "invite_url": invite_url,
                "feuser_recipient": invitee,
            },
            recipient_email=invite.invitee_email,
            notification_class="group_activity",
        )

    @staticmethod
    def send_group_onboarding_invite(invite: BuddyOnboardingInvite):
        site_url = getattr(settings, "SITE_URL", "")
        register_url = f"{site_url}/register/"
        BuddyEmailService._send(
            subject=f"{_display_name(invite.inviting_feuser)} invited you to join their project on Comaney",
            template="emails/buddy_onboarding_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviting_feuser),
                "dummy_name": (invite.dummy.display_name + " (offline member)") if invite.dummy_id else None,
                "is_merge": bool(invite.dummy_id),
                "is_group": True,
                "group_name": invite.group.name if invite.group_id else None,
                "register_url": register_url,
            },
            recipient_email=invite.invitee_email,
            respect_prefs=False,
        )

    @staticmethod
    def send_expense_approval_request(expense, initiating_feuser):
        site_url = getattr(settings, "SITE_URL", "")
        review_url = f"{site_url}/buddies/expense/{expense.uid}/review/"
        BuddyEmailService._send(
            subject=f"New shared expense needs your approval: {expense.title}",
            template="emails/buddy_expense_approval.html",
            ctx={
                "expense": expense,
                "initiating_name": _display_name(initiating_feuser),
                "review_url": review_url,
                "feuser_recipient": expense.owning_feuser,
            },
            recipient_email=expense.owning_feuser.email,
            notification_class="expense_assignments",
        )

    @staticmethod
    def send_rejection_notification(expense, rejecting_feuser, notifying_feuser, owner_rejected=False):
        site_url = getattr(settings, "SITE_URL", "")
        BuddyEmailService._send(
            subject=f"Shared expense declined by {_display_name(rejecting_feuser)}: {expense.title}",
            template="emails/buddy_expense_rejected.html",
            ctx={
                "expense": expense,
                "rejecting_name": _display_name(rejecting_feuser),
                "feuser_recipient": notifying_feuser,
                "owner_rejected": owner_rejected,
            },
            recipient_email=notifying_feuser.email,
            notification_class="expense_participation",
        )

    @staticmethod
    def send_merge_invite(invite: DummyMergeInvite):
        site_url = getattr(settings, "SITE_URL", "")
        merge_url = f"{site_url}/buddies/merge/{invite.token}/"
        group = invite.dummy.owning_group
        is_group_merge = group is not None
        subject = (
            f"{_display_name(invite.inviting_feuser)} wants to add you to the group \"{group.name}\" on Comaney"
            if is_group_merge else
            f"{_display_name(invite.inviting_feuser)} wants to link your account with their buddy record on Comaney"
        )
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_merge_invite.html",
            ctx={
                "invite": invite,
                "inviting_name": _display_name(invite.inviting_feuser),
                "dummy_name": invite.dummy.display_name + " (offline member)",
                "merge_url": merge_url,
                "feuser_recipient": invite.invited_feuser,
                "is_group_merge": is_group_merge,
                "group_name": group.name if is_group_merge else None,
            },
            recipient_email=invite.invited_feuser.email,
            notification_class="group_activity",
        )

    @staticmethod
    def send_onboarding_invite(invite: BuddyOnboardingInvite):
        site_url = getattr(settings, "SITE_URL", "")
        register_url = f"{site_url}/register/"
        is_merge = invite.dummy_id is not None
        subject = (
            f"{_display_name(invite.inviting_feuser)} wants to link a buddy record with your account on Comaney"
            if is_merge else
            f"{_display_name(invite.inviting_feuser)} invited you to be spending buddies on Comaney"
        )
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_onboarding_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviting_feuser),
                "dummy_name": (invite.dummy.display_name + " (offline member)") if is_merge else None,
                "is_merge": is_merge,
                "is_group": False,
                "group_name": None,
                "register_url": register_url,
            },
            recipient_email=invite.invitee_email,
            respect_prefs=False,
        )

    @staticmethod
    def send_settlement_confirmation_request(expense, acting_feuser, creditor_feuser, debtor_name: str):
        """Email sent to the creditor of an individual group settlement asking them to confirm receipt."""
        site_url = getattr(settings, "SITE_URL", "")
        confirm_url = f"{site_url}/buddies/expense/{expense.uid}/approve-settlement/"
        group_name = expense.project.name if expense.project_id else None
        subject = (
            f"{debtor_name} recorded a settlement with you in {group_name}"
            if group_name
            else f"{debtor_name} recorded a settlement with you"
        )
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_settlement_creditor_confirm.html",
            ctx={
                "expense": expense,
                "acting_name": _display_name(acting_feuser),
                "debtor_name": debtor_name,
                "confirm_url": confirm_url,
                "feuser_recipient": creditor_feuser,
            },
            recipient_email=creditor_feuser.email,
            notification_class="settlements",
        )

    @staticmethod
    def send_direct_settlement_confirmation_request(expense, debtor_feuser, creditor_feuser):
        """Email sent to the creditor of a direct (non-group) buddy settlement."""
        debtor_name = _display_name(debtor_feuser)
        BuddyEmailService.send_settlement_confirmation_request(
            expense, debtor_feuser, creditor_feuser, debtor_name
        )

    @staticmethod
    def send_settlement_approved_notification(expense, creditor_feuser, debtor_feuser):
        """Email sent to the debtor when the creditor confirms receipt of their settlement."""
        creditor_name = _display_name(creditor_feuser)
        group_name = expense.project.name if expense.project_id else None
        subject = (
            f"{creditor_name} confirmed your settlement in {group_name}"
            if group_name
            else f"{creditor_name} confirmed your settlement"
        )
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_settlement_approved.html",
            ctx={
                "expense": expense,
                "creditor_name": creditor_name,
                "feuser_recipient": debtor_feuser,
            },
            recipient_email=debtor_feuser.email,
            notification_class="settlements",
        )

    @staticmethod
    def send_settlement_rejection_notification(expense, creditor_feuser, debtor_feuser):
        """Email sent to the debtor when the creditor rejects their settlement record."""
        creditor_name = _display_name(creditor_feuser)
        group_name = expense.project.name if expense.project_id else None
        subject = (
            f"{creditor_name} rejected your settlement in {group_name}"
            if group_name
            else f"{creditor_name} rejected your settlement"
        )
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_settlement_rejected.html",
            ctx={
                "expense": expense,
                "creditor_name": creditor_name,
                "feuser_recipient": debtor_feuser,
            },
            recipient_email=debtor_feuser.email,
            notification_class="settlements",
        )

    @staticmethod
    def send_group_settlement_emails(admin_feuser, group, settlements: list):
        """Send summary emails after a group-wide settlement."""
        site_url = getattr(settings, "SITE_URL", "")

        debtor_map: dict = {}
        creditor_map: dict = {}
        dummy_creditor_items: list = []

        for s in settlements:
            if s["auto_approve"]:
                continue

            if s["debtor_feuser"] and s["debtor_feuser"].pk != admin_feuser.pk:
                pk = s["debtor_feuser"].pk
                if pk not in debtor_map:
                    debtor_map[pk] = {"feuser": s["debtor_feuser"], "items": []}
                debtor_map[pk]["items"].append((s["creditor_name"], s["amount"]))

            if s["creditor_feuser"]:
                pk = s["creditor_feuser"].pk
                confirm_url = f"{site_url}/buddies/expense/{s['expense'].uid}/approve-settlement/"
                if pk not in creditor_map:
                    creditor_map[pk] = {"feuser": s["creditor_feuser"], "items": []}
                creditor_map[pk]["items"].append((s["debtor_name"], s["amount"], confirm_url))
            elif s["creditor_dummy"]:
                dummy_creditor_items.append({
                    "dummy": s["creditor_dummy"],
                    "debtor_name": s["debtor_name"],
                    "amount": s["amount"],
                    "expense": s["expense"],
                })

        for info in debtor_map.values():
            BuddyEmailService._send(
                subject=f"Group settlement for {group.name}: payments due",
                template="emails/buddy_group_settlement_debtor.html",
                ctx={
                    "group": group,
                    "items": info["items"],
                    "feuser_recipient": info["feuser"],
                    "admin_name": _display_name(admin_feuser),
                },
                recipient_email=info["feuser"].email,
                notification_class="settlements",
            )

        for info in creditor_map.values():
            BuddyEmailService._send(
                subject=f"Group settlement for {group.name}: please confirm receipts",
                template="emails/buddy_group_settlement_creditor.html",
                ctx={
                    "group": group,
                    "items": info["items"],
                    "feuser_recipient": info["feuser"],
                    "admin_name": _display_name(admin_feuser),
                },
                recipient_email=info["feuser"].email,
                notification_class="settlements",
            )

        if dummy_creditor_items:
            BuddyEmailService._send(
                subject=f"Group settlement for {group.name}: offline member receipts",
                template="emails/buddy_group_settlement_admin_dummies.html",
                ctx={
                    "group": group,
                    "items": dummy_creditor_items,
                    "feuser_recipient": admin_feuser,
                    "admin_name": _display_name(admin_feuser),
                },
                recipient_email=admin_feuser.email,
                respect_prefs=False,
            )

    @staticmethod
    def send_group_removed_notification(removed_feuser, admin_feuser, group):
        BuddyEmailService._send(
            subject=f"You have been removed from the group \"{group.name}\"",
            template="emails/buddy_group_removed.html",
            ctx={
                "group_name": group.name,
                "admin_name": _display_name(admin_feuser),
                "feuser_recipient": removed_feuser,
            },
            recipient_email=removed_feuser.email,
            notification_class="group_activity",
        )

    @staticmethod
    def send_group_invite_accepted(invite: "BuddyGroupInvite", acceptee_name: str):
        BuddyEmailService._send(
            subject=f"{acceptee_name} joined your group \"{invite.group.name}\"",
            template="emails/buddy_group_invite_accepted.html",
            ctx={
                "acceptee_name": acceptee_name,
                "group_name": invite.group.name,
                "feuser_recipient": invite.inviting_feuser,
            },
            recipient_email=invite.inviting_feuser.email,
            notification_class="group_activity",
        )

    @staticmethod
    def send_group_invite_declined(invite: "BuddyGroupInvite", decliner_name: str):
        BuddyEmailService._send(
            subject=f"{decliner_name} declined your invitation to \"{invite.group.name}\"",
            template="emails/buddy_group_invite_declined.html",
            ctx={
                "decliner_name": decliner_name,
                "group_name": invite.group.name,
                "feuser_recipient": invite.inviting_feuser,
            },
            recipient_email=invite.inviting_feuser.email,
            notification_class="group_activity",
        )

    @staticmethod
    def send_expense_unlinked_notification(expense, admin_feuser, group, notify_feuser, is_owner: bool):
        site_url = getattr(settings, "SITE_URL", "")
        BuddyEmailService._send(
            subject=f"An expense was unlinked from {group.name} by the group admin",
            template="emails/buddy_expense_unlinked.html",
            ctx={
                "admin_name": _display_name(admin_feuser),
                "expense_title": expense.title,
                "group_name": group.name,
                "group_id": group.uid,
                "is_owner": is_owner,
                "feuser_recipient": notify_feuser,
            },
            recipient_email=notify_feuser.email,
            notification_class="group_activity",
        )

    @staticmethod
    def send_settlement_updated_notification(expense, creditor_feuser):
        """Sent to the creditor when the debtor edits an unapproved settlement."""
        if expense.is_dummy and expense.upfront_payee_dummy_id:
            debtor_name = expense.upfront_payee_dummy.display_name + " (offline member)"
        else:
            debtor_name = _display_name(expense.owning_feuser)
        group_name = expense.project.name if expense.project_id else None
        subject = (
            f"{debtor_name} updated their settlement in {group_name}"
            if group_name
            else f"{debtor_name} updated their settlement with you"
        )
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_settlement_updated.html",
            ctx={
                "expense_title": expense.title,
                "expense_value": expense.value,
                "debtor_name": debtor_name,
                "group_name": group_name,
                "currency": expense.owning_feuser.currency,
                "feuser_recipient": creditor_feuser,
            },
            recipient_email=creditor_feuser.email,
            notification_class="settlements",
        )

    @staticmethod
    def send_settlement_cancelled_notification(expense, creditor_feuser):
        """Sent to the creditor when the debtor deletes an unapproved settlement."""
        if expense.is_dummy and expense.upfront_payee_dummy_id:
            debtor_name = expense.upfront_payee_dummy.display_name + " (offline member)"
        else:
            debtor_name = _display_name(expense.owning_feuser)
        group_name = expense.project.name if expense.project_id else None
        subject = (
            f"{debtor_name} cancelled their settlement in {group_name}"
            if group_name
            else f"{debtor_name} cancelled their settlement with you"
        )
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_settlement_cancelled.html",
            ctx={
                "expense_title": expense.title,
                "expense_value": expense.value,
                "debtor_name": debtor_name,
                "group_name": group_name,
                "currency": expense.owning_feuser.currency,
                "feuser_recipient": creditor_feuser,
            },
            recipient_email=creditor_feuser.email,
            notification_class="settlements",
        )

    @staticmethod
    def send_kicked_notification(kicked_feuser, kicking_display_name: str):
        site_url = getattr(settings, "SITE_URL", "")
        BuddyEmailService._send(
            subject=f"{kicking_display_name} removed you as a spending buddy on Comaney",
            template="emails/buddy_kicked.html",
            ctx={
                "kicking_name": kicking_display_name,
                "feuser_recipient": kicked_feuser,
            },
            recipient_email=kicked_feuser.email,
            notification_class="group_activity",
        )

    # ------------------------------------------------------------------
    # Buddy expense participation notifications
    # ------------------------------------------------------------------

    @staticmethod
    def _build_expense_rows(expense):
        """
        Returns (payer_row, participant_rows) for use in email templates.
        payer_row: dict with name, share_percent, share_value, is_payer=True
        participant_rows: list of dicts with same keys plus is_payer=False
        """
        spendings = list(
            expense.buddy_spendings
            .select_related("participant_feuser", "participant_dummy")
            .all()
        )
        participant_sum = sum(bs.share_percent for bs in spendings) if spendings else Decimal("0")
        payer_share = Decimal("100") - participant_sum
        payer_value = expense.value * payer_share / Decimal("100")

        if expense.is_dummy and expense.upfront_payee_dummy_id:
            payer_name = expense.upfront_payee_dummy.display_name + " (offline member)"
        else:
            payer_name = _display_name(expense.owning_feuser)

        payer_row = {
            "name": payer_name,
            "share_percent": payer_share,
            "share_value": payer_value,
            "is_payer": True,
        }

        participant_rows = []
        for bs in spendings:
            if bs.participant_feuser_id:
                name = _display_name(bs.participant_feuser)
            else:
                name = bs.participant_dummy.display_name + " (offline member)"
            participant_rows.append({
                "name": name,
                "share_percent": bs.share_percent,
                "share_value": expense.value * bs.share_percent / Decimal("100"),
                "is_payer": False,
            })

        return payer_row, participant_rows

    @staticmethod
    def send_expense_participant_notice(
        expense, actor_feuser, recipient_feuser, currency, is_added_to_existing=False
    ):
        """Notify a participant that they have been included in a shared expense."""
        actor_name = _display_name(actor_feuser)
        bs = expense.buddy_spendings.filter(participant_feuser=recipient_feuser).first()
        if bs is None:
            return
        share_percent = bs.share_percent
        share_value = expense.value * share_percent / Decimal("100")
        payer_row, participant_rows = BuddyEmailService._build_expense_rows(expense)
        subject = (
            f"{actor_name} added you to a shared expense: {expense.title}"
            if is_added_to_existing
            else f"{actor_name} included you in a shared expense: {expense.title}"
        )
        site_url = getattr(settings, "SITE_URL", "")
        approve_url = f"{site_url}/buddies/expense/{expense.uid}/participant-approve/"
        reject_url = f"{site_url}/buddies/expense/{expense.uid}/participant-reject/"
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_expense_participant_notice.html",
            ctx={
                "expense": expense,
                "actor_name": actor_name,
                "share_percent": share_percent,
                "share_value": share_value,
                "payer_row": payer_row,
                "participant_rows": participant_rows,
                "currency": currency,
                "is_added_to_existing": is_added_to_existing,
                "feuser_recipient": recipient_feuser,
                "approve_url": approve_url,
                "reject_url": reject_url,
            },
            recipient_email=recipient_feuser.email,
            notification_class="expense_participation",
        )

    @staticmethod
    def send_participant_approval_notification(expense, participant_feuser, new_state):
        """Notify the upfront payer (or group admin) when a participant changes their approval state."""
        from ..models import BuddySpending

        if expense.is_dummy:
            if expense.project_id and expense.project:
                notify_feuser = expense.project.admin_feuser
            else:
                notify_feuser = expense.owning_feuser
        else:
            notify_feuser = expense.owning_feuser

        if notify_feuser.pk == participant_feuser.pk:
            return

        participant_name = _display_name(participant_feuser)
        state_label = {
            BuddySpending.APPROVAL_APPROVED: "approved",
            BuddySpending.APPROVAL_REJECTED: "rejected",
            BuddySpending.APPROVAL_NEUTRAL: "reset their decision on",
        }.get(new_state, "changed their decision on")

        group_name = expense.project.name if expense.project_id else None
        subject = (
            f"{participant_name} {state_label} a shared expense in {group_name}: {expense.title}"
            if group_name
            else f"{participant_name} {state_label} a shared expense: {expense.title}"
        )
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_participant_approval_changed.html",
            ctx={
                "expense": expense,
                "participant_name": participant_name,
                "new_state": new_state,
                "state_label": state_label,
                "group_name": group_name,
                "feuser_recipient": notify_feuser,
                "APPROVAL_APPROVED": BuddySpending.APPROVAL_APPROVED,
                "APPROVAL_REJECTED": BuddySpending.APPROVAL_REJECTED,
            },
            recipient_email=notify_feuser.email,
            notification_class="participant_decisions",
        )

    @staticmethod
    def send_expense_updated_notice(expense, actor_feuser, recipient_feuser, currency, changes):
        """Notify an existing participant that a shared expense was updated."""
        actor_name = _display_name(actor_feuser)
        bs = expense.buddy_spendings.filter(participant_feuser=recipient_feuser).first()
        share_percent = bs.share_percent if bs else None
        share_value = (expense.value * share_percent / Decimal("100")) if share_percent is not None else None
        payer_row, participant_rows = BuddyEmailService._build_expense_rows(expense)
        BuddyEmailService._send(
            subject=f"{actor_name} updated a shared expense: {expense.title}",
            template="emails/buddy_expense_updated.html",
            ctx={
                "expense": expense,
                "actor_name": actor_name,
                "share_percent": share_percent,
                "share_value": share_value,
                "payer_row": payer_row,
                "participant_rows": participant_rows,
                "currency": currency,
                "changes": changes,
                "feuser_recipient": recipient_feuser,
            },
            recipient_email=recipient_feuser.email,
            notification_class="expense_participation",
        )

    @staticmethod
    def send_expense_removed_notice(
        expense, actor_feuser, recipient_feuser, currency,
        old_share_percent, old_share_value, old_title,
    ):
        """Notify a participant who was removed from a shared expense."""
        actor_name = _display_name(actor_feuser)
        BuddyEmailService._send(
            subject=f"{actor_name} removed you from a shared expense: {old_title}",
            template="emails/buddy_expense_removed.html",
            ctx={
                "expense": expense,
                "actor_name": actor_name,
                "old_title": old_title,
                "old_share_percent": old_share_percent,
                "old_share_value": old_share_value,
                "currency": currency,
                "feuser_recipient": recipient_feuser,
            },
            recipient_email=recipient_feuser.email,
            notification_class="expense_participation",
        )

    @staticmethod
    def notify_expense_created(expense, actor_feuser):
        """
        High-level: notify all real feuser participants (except actor) that they
        are included in a new buddy expense. Skips settlement expenses.
        """
        if getattr(expense, "is_buddies_settlement", False):
            return
        currency = actor_feuser.currency
        for bs in expense.buddy_spendings.select_related("participant_feuser").filter(
            participant_feuser__isnull=False
        ):
            recipient = bs.participant_feuser
            if recipient.pk == actor_feuser.pk:
                continue
            BuddyEmailService.send_expense_participant_notice(expense, actor_feuser, recipient, currency)

    @staticmethod
    def notify_expense_updated(
        expense, actor_feuser, old_title, old_value, old_participants,
        extra_notify_feuser=None,
    ):
        """
        High-level: notify participants of changes to a buddy expense.

        old_participants: {feuser_pk: (feuser, share_percent)} snapshot taken before editing.
        extra_notify_feuser: optional FeUser to also notify (e.g. expense owner in admin edits).
        Skips settlement expenses.
        """
        if getattr(expense, "is_buddies_settlement", False):
            return

        currency = actor_feuser.currency

        new_participants = {
            bs.participant_feuser_id: (bs.participant_feuser, bs.share_percent)
            for bs in expense.buddy_spendings.select_related("participant_feuser").filter(
                participant_feuser__isnull=False
            )
        }

        old_pks = set(old_participants.keys())
        new_pks = set(new_participants.keys())
        added_pks = new_pks - old_pks
        removed_pks = old_pks - new_pks
        share_changed_pks = {
            pk for pk in (old_pks & new_pks)
            if old_participants[pk][1] != new_participants[pk][1]
        }

        title_changed = old_title != expense.title
        value_changed = old_value != expense.value
        buddy_changed = bool(added_pks or removed_pks or share_changed_pks)

        if not (title_changed or value_changed or buddy_changed):
            return

        added_names = [_display_name(new_participants[pk][0]) for pk in added_pks]
        removed_names = [_display_name(old_participants[pk][0]) for pk in removed_pks]

        changes = {
            "title_changed": title_changed,
            "old_title": old_title,
            "value_changed": value_changed,
            "old_value": old_value,
            "participants_added": added_names,
            "participants_removed": removed_names,
        }

        # Notify newly added participants
        for pk in added_pks:
            feuser, _ = new_participants[pk]
            if feuser.pk == actor_feuser.pk:
                continue
            BuddyEmailService.send_expense_participant_notice(
                expense, actor_feuser, feuser, currency, is_added_to_existing=True
            )

        # Notify existing participants of changes
        for pk in (old_pks & new_pks):
            feuser, _ = new_participants[pk]
            if feuser.pk == actor_feuser.pk:
                continue
            if title_changed or value_changed or pk in share_changed_pks or added_pks or removed_pks:
                BuddyEmailService.send_expense_updated_notice(
                    expense, actor_feuser, feuser, currency, changes
                )

        # Notify removed participants
        for pk in removed_pks:
            feuser, old_share_percent = old_participants[pk]
            if feuser.pk == actor_feuser.pk:
                continue
            old_share_value = old_value * old_share_percent / Decimal("100")
            BuddyEmailService.send_expense_removed_notice(
                expense, actor_feuser, feuser, currency,
                old_share_percent=old_share_percent,
                old_share_value=old_share_value,
                old_title=old_title,
            )

        # Optionally notify the expense owner (admin edit scenario)
        if extra_notify_feuser and extra_notify_feuser.pk != actor_feuser.pk:
            if extra_notify_feuser.pk not in new_pks and extra_notify_feuser.pk not in removed_pks:
                BuddyEmailService.send_expense_updated_notice(
                    expense, actor_feuser, extra_notify_feuser, currency, changes
                )
