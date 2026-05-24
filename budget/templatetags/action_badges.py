"""
Reusable action badge template tag.

Usage in templates:
    {% load action_badges %}
    {% action_badge current_feuser "partnership" %}

To register a new badge type elsewhere:
    from budget.templatetags.action_badges import register_badge

    @register_badge("my_type")
    def _count_my_type(feuser):
        return MyModel.objects.filter(feuser=feuser, pending=True).count()
"""
from django import template

register = template.Library()

_BADGE_COUNTERS: dict = {}


def register_badge(badge_type: str):
    """Decorator: register a counter function for badge_type."""
    def decorator(fn):
        _BADGE_COUNTERS[badge_type] = fn
        return fn
    return decorator


def _count_actions(feuser, badge_type: str) -> int:
    fn = _BADGE_COUNTERS.get(badge_type)
    if fn is None:
        return 0
    try:
        return fn(feuser) or 0
    except Exception:
        return 0


@register.inclusion_tag("partials/action_badge.html")
def action_badge(feuser, badge_type: str):
    count = _count_actions(feuser, badge_type) if feuser else 0
    return {"count": count}


# ---------------------------------------------------------------------------
# Built-in registrations
# ---------------------------------------------------------------------------

@register.inclusion_tag("partials/partnership_stoerer.html")
def partnership_stoerer(feuser):
    """Render the pending-onboarding banner if the user has a pending invite."""
    if not feuser:
        return {"wizard_url": None, "invite": None}
    from buddies.models import CatalogPartnershipInvite
    invite = CatalogPartnershipInvite.objects.filter(
        invitee_email=feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    ).select_related("inviter").first()
    if invite:
        return {"wizard_url": f"/buddies/partnership/accept/{invite.token}/", "invite": invite}
    return {"wizard_url": None, "invite": None}


@register.simple_tag
def partnership_invite_state(viewer_feuser, target_feuser):
    """
    Returns: 'partner' | 'pending' | 'invite' | 'unavailable'
    - partner:     target is already in the same partnership as viewer
    - pending:     an invite to target is already pending
    - invite:      viewer can invite target
    - unavailable: target is in a different partnership (cannot be invited)
    """
    from buddies.models import CatalogPartnershipMembership, CatalogPartnershipInvite
    try:
        my_m = viewer_feuser.catalog_membership
        try:
            their_m = target_feuser.catalog_membership
            if their_m.partnership_id == my_m.partnership_id:
                return "partner"
            return "unavailable"
        except CatalogPartnershipMembership.DoesNotExist:
            pass
    except CatalogPartnershipMembership.DoesNotExist:
        try:
            target_feuser.catalog_membership
            return "unavailable"
        except CatalogPartnershipMembership.DoesNotExist:
            pass

    if CatalogPartnershipInvite.objects.filter(
        invitee_email=target_feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    ).exists():
        return "pending"
    return "invite"


@register_badge("partnership")
def _count_partnership_actions(feuser) -> int:
    from buddies.models import CatalogPartnershipInvite, CatalogPartnershipMembership
    pending_invites = CatalogPartnershipInvite.objects.filter(
        invitee_email=feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    ).count()
    pending_onboarding = 0
    try:
        m = feuser.catalog_membership
        if not m.onboarding_complete:
            pending_onboarding = 1
    except CatalogPartnershipMembership.DoesNotExist:
        pass
    return pending_invites + pending_onboarding
