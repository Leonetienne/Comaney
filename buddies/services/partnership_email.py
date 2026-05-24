"""
Partnership event email notifications.
Respects notify_own_partnership_changes and notify_someones_partnership_changes.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string


def _send(subject: str, template: str, ctx: dict, recipient_email: str) -> bool:
    if settings.DISABLE_EMAILING:
        return False
    feuser = ctx.get("feuser_recipient")
    if feuser and not feuser.email_notifications:
        return False
    if feuser and feuser.is_demo:
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


def _name(feuser) -> str:
    parts = [feuser.first_name, feuser.last_name]
    full = " ".join(p for p in parts if p).strip()
    return full or feuser.email


def notify_partner_event(recipient, event: str, **kwargs) -> None:
    """
    Dispatch a partnership notification email.

    Events and their required kwargs:
      invite_sent        — invite (CatalogPartnershipInvite)
      invite_accepted    — invitee (FeUser)
      invite_declined    — invitee (FeUser)
      new_partner_joined — joined (FeUser)
      kicked_self        — (no extra kwargs; recipient is the kicked user)
      partner_kicked     — kicked (FeUser)
      partner_left       — left (FeUser)
      partner_disconnected — removed (FeUser)
    """
    site_url = getattr(settings, "SITE_URL", "")

    if event == "invite_sent":
        if not recipient.notify_own_partnership_changes:
            return
        invite = kwargs["invite"]
        onboarding_url = f"{site_url}/buddies/partnership/accept/{invite.token}/"
        _send(
            subject="You've been invited to a Catalog Partnership",
            template="emails/partnership_invite.html",
            ctx={
                "feuser_recipient": recipient,
                "inviter_name": _name(invite.inviter),
                "onboarding_url": onboarding_url,
            },
            recipient_email=recipient.email,
        )

    elif event == "invite_accepted":
        if not recipient.notify_own_partnership_changes:
            return
        invitee = kwargs["invitee"]
        _send(
            subject="Your Catalog Partnership invitation was accepted",
            template="emails/partnership_invite_accepted.html",
            ctx={
                "feuser_recipient": recipient,
                "invitee_name": _name(invitee),
            },
            recipient_email=recipient.email,
        )

    elif event == "invite_declined":
        if not recipient.notify_own_partnership_changes:
            return
        invitee = kwargs["invitee"]
        _send(
            subject="Your Catalog Partnership invitation was declined",
            template="emails/partnership_invite_declined.html",
            ctx={
                "feuser_recipient": recipient,
                "invitee_name": _name(invitee),
            },
            recipient_email=recipient.email,
        )

    elif event == "new_partner_joined":
        if not recipient.notify_someones_partnership_changes:
            return
        joined = kwargs["joined"]
        _send(
            subject="A new partner is in the house!",
            template="emails/partnership_new_member.html",
            ctx={
                "feuser_recipient": recipient,
                "joined_name": _name(joined),
            },
            recipient_email=recipient.email,
        )

    elif event == "kicked_self":
        if not recipient.notify_own_partnership_changes:
            return
        _send(
            subject="You have been removed from a Catalog Partnership",
            template="emails/partnership_kicked.html",
            ctx={"feuser_recipient": recipient},
            recipient_email=recipient.email,
        )

    elif event == "partner_kicked":
        if not recipient.notify_someones_partnership_changes:
            return
        kicked = kwargs["kicked"]
        _send(
            subject="A partner has been removed from your Catalog Partnership",
            template="emails/partnership_partner_kicked.html",
            ctx={
                "feuser_recipient": recipient,
                "kicked_name": _name(kicked),
            },
            recipient_email=recipient.email,
        )

    elif event == "partner_left":
        if not recipient.notify_someones_partnership_changes:
            return
        left = kwargs["left"]
        _send(
            subject="A partner has left your Catalog Partnership",
            template="emails/partnership_partner_left.html",
            ctx={
                "feuser_recipient": recipient,
                "left_name": _name(left),
            },
            recipient_email=recipient.email,
        )

    elif event == "partner_disconnected":
        if not recipient.notify_someones_partnership_changes:
            return
        removed = kwargs["removed"]
        _send(
            subject="A partner was removed: no mutual connection remaining",
            template="emails/partnership_partner_disconnected.html",
            ctx={
                "feuser_recipient": recipient,
                "removed_name": _name(removed),
            },
            recipient_email=recipient.email,
        )
