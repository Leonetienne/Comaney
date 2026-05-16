from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from ..models import BuddyInvite, BuddyGroupInvite, BuddyOnboardingInvite, DummyMergeInvite
from ._helpers import _display_name


class BuddyEmailService:
    """All buddy-related email sending. Respects DISABLE_EMAILING and email_notifications."""

    @staticmethod
    def _send(subject: str, template: str, ctx: dict, recipient_email: str, respect_prefs: bool = True):
        if settings.DISABLE_EMAILING:
            return False

        if respect_prefs:
            feuser = ctx.get("feuser_recipient")
            if feuser and not feuser.email_notifications:
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
        site_url = getattr(settings, "SITE_URL", "")
        invite_url = f"{site_url}/buddies/invite/{invite.token}/"
        BuddyEmailService._send(
            subject=f"{_display_name(invite.inviter)} invited you to be spending buddies on Comaney",
            template="emails/buddy_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviter),
                "invite_url": invite_url,
            },
            recipient_email=invite.invitee_email,
            respect_prefs=False,
        )

    @staticmethod
    def send_group_invite(invite: BuddyGroupInvite, invitee):
        site_url = getattr(settings, "SITE_URL", "")
        invite_url = f"{site_url}/buddies/group-invite/{invite.token}/"
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
        )

    @staticmethod
    def send_group_onboarding_invite(invite: BuddyOnboardingInvite):
        site_url = getattr(settings, "SITE_URL", "")
        register_url = f"{site_url}/register/"
        BuddyEmailService._send(
            subject=f"{_display_name(invite.inviting_feuser)} invited you to join their group on Comaney",
            template="emails/buddy_onboarding_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviting_feuser),
                "dummy_name": invite.dummy.display_name if invite.dummy_id else None,
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
        approve_url = f"{site_url}/buddies/expense/{expense.uid}/approve/"
        reject_url = f"{site_url}/buddies/expense/{expense.uid}/reject/"
        BuddyEmailService._send(
            subject=f"New shared expense needs your approval: {expense.title}",
            template="emails/buddy_expense_approval.html",
            ctx={
                "expense": expense,
                "initiating_name": _display_name(initiating_feuser),
                "approve_url": approve_url,
                "reject_url": reject_url,
                "feuser_recipient": expense.owning_feuser,
            },
            recipient_email=expense.owning_feuser.email,
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
                "dummy_name": invite.dummy.display_name,
                "merge_url": merge_url,
                "feuser_recipient": invite.invited_feuser,
                "is_group_merge": is_group_merge,
                "group_name": group.name if is_group_merge else None,
            },
            recipient_email=invite.invited_feuser.email,
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
                "dummy_name": invite.dummy.display_name if is_merge else None,
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
        group_name = expense.buddy_group.name if expense.buddy_group_id else None
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
        group_name = expense.buddy_group.name if expense.buddy_group_id else None
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
        )

    @staticmethod
    def send_settlement_rejection_notification(expense, creditor_feuser, debtor_feuser):
        """Email sent to the debtor when the creditor rejects their settlement record."""
        creditor_name = _display_name(creditor_feuser)
        group_name = expense.buddy_group.name if expense.buddy_group_id else None
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
        )
