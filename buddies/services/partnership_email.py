"""Partnership event notifications. Routes through emit_notification."""


def _name(feuser) -> str:
    parts = [feuser.first_name, feuser.last_name]
    full = " ".join(p for p in parts if p).strip()
    return full or feuser.email


def notify_partner_event(recipient, event: str, **kwargs) -> None:
    """
    Dispatch a partnership notification (DB record + optional email).

    Events and their required kwargs:
      invite_sent          — invite (CatalogPartnershipInvite)
      invite_accepted      — invitee (FeUser)
      invite_declined      — invitee (FeUser)
      new_partner_joined   — joined (FeUser)
      kicked_self          — (no extra kwargs; recipient is the kicked user)
      partner_kicked       — kicked (FeUser)
      partner_left         — left (FeUser)
      partner_disconnected — removed (FeUser)
    """
    from django.conf import settings
    from feusers.notifications_service import emit_notification

    site_url = getattr(settings, "SITE_URL", "")

    if event == "invite_sent":
        invite = kwargs["invite"]
        onboarding_url = f"{site_url}/buddies/partnership/accept/{invite.token}/"
        inviter_name = _name(invite.inviter)
        emit_notification(
            recipient,
            type="own_partnership_changes",
            subject="You've been invited to a Catalog Partnership",
            message=f"{inviter_name} invited you to join their Catalog Partnership.",
            related_feuser=invite.inviter,
            email_template="emails/partnership_invite.html",
            email_ctx={"feuser_recipient": recipient, "inviter_name": inviter_name,
                       "onboarding_url": onboarding_url},
        )

    elif event == "invite_accepted":
        invitee = kwargs["invitee"]
        invitee_name = _name(invitee)
        emit_notification(
            recipient,
            type="own_partnership_changes",
            subject="Your Catalog Partnership invitation was accepted",
            message=f"{invitee_name} accepted your Catalog Partnership invitation.",
            related_feuser=invitee,
            email_template="emails/partnership_invite_accepted.html",
            email_ctx={"feuser_recipient": recipient, "invitee_name": invitee_name},
        )

    elif event == "invite_declined":
        invitee = kwargs["invitee"]
        invitee_name = _name(invitee)
        emit_notification(
            recipient,
            type="own_partnership_changes",
            subject="Your Catalog Partnership invitation was declined",
            message=f"{invitee_name} declined your Catalog Partnership invitation.",
            related_feuser=invitee,
            email_template="emails/partnership_invite_declined.html",
            email_ctx={"feuser_recipient": recipient, "invitee_name": invitee_name},
        )

    elif event == "new_partner_joined":
        joined = kwargs["joined"]
        joined_name = _name(joined)
        emit_notification(
            recipient,
            type="someones_partnership_changes",
            subject="A new partner is in the house!",
            message=f"{joined_name} joined your Catalog Partnership.",
            related_feuser=joined,
            email_template="emails/partnership_new_member.html",
            email_ctx={"feuser_recipient": recipient, "joined_name": joined_name},
        )

    elif event == "kicked_self":
        emit_notification(
            recipient,
            type="own_partnership_changes",
            subject="You have been removed from a Catalog Partnership",
            message="You have been removed from a Catalog Partnership.",
            email_template="emails/partnership_kicked.html",
            email_ctx={"feuser_recipient": recipient},
        )

    elif event == "partner_kicked":
        kicked = kwargs["kicked"]
        kicked_name = _name(kicked)
        emit_notification(
            recipient,
            type="someones_partnership_changes",
            subject="A partner has been removed from your Catalog Partnership",
            message=f"{kicked_name} was removed from your Catalog Partnership.",
            related_feuser=kicked,
            email_template="emails/partnership_partner_kicked.html",
            email_ctx={"feuser_recipient": recipient, "kicked_name": kicked_name},
        )

    elif event == "partner_left":
        left = kwargs["left"]
        left_name = _name(left)
        emit_notification(
            recipient,
            type="someones_partnership_changes",
            subject="A partner has left your Catalog Partnership",
            message=f"{left_name} left your Catalog Partnership.",
            related_feuser=left,
            email_template="emails/partnership_partner_left.html",
            email_ctx={"feuser_recipient": recipient, "left_name": left_name},
        )

    elif event == "partner_disconnected":
        removed = kwargs["removed"]
        removed_name = _name(removed)
        emit_notification(
            recipient,
            type="someones_partnership_changes",
            subject="A partner was removed: no mutual connection remaining",
            message=f"{removed_name} was removed; no mutual connection remains.",
            related_feuser=removed,
            email_template="emails/partnership_partner_disconnected.html",
            email_ctx={"feuser_recipient": recipient, "removed_name": removed_name},
        )
