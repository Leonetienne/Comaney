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


@register.simple_tag
def buddy_invite_state(viewer_feuser, target_feuser):
    """
    Returns: 'buddy' | 'pending' | 'invite'
    - buddy:   viewer and target are already direct buddies
    - pending: viewer already has an outgoing invite to target
    - invite:  viewer can invite target as a direct buddy
    """
    from buddies.services.query import BuddyQueryService
    if BuddyQueryService.are_buddies(viewer_feuser, target_feuser):
        return "buddy"
    if BuddyQueryService.has_pending_invite_to(viewer_feuser, target_feuser):
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


@register_badge("buddies")
def _count_buddy_actions(feuser) -> int:
    from django.utils import timezone
    from buddies.models import BuddyInvite, DummyMergeInvite
    now = timezone.now()
    incoming = BuddyInvite.objects.filter(
        invitee_email=feuser.email,
        expires_at__gt=now,
    ).count()
    merge_in = DummyMergeInvite.objects.filter(
        invited_feuser=feuser,
        expires_at__gt=now,
    ).count()
    return incoming + merge_in


@register_badge("buddy_expenses")
def _count_buddy_expense_actions(feuser) -> int:
    from budget.models import Expense
    from buddies.models import Project
    count = 0
    # Personal expenses where feuser is recorded as upfront payer and needs to confirm
    count += Expense.objects.filter(
        owning_feuser=feuser,
        buddy_approved=False,
        is_buddies_settlement=False,
        project__isnull=True,
    ).count()
    # Settlements where feuser is the creditor (all contexts, including projects)
    count += Expense.objects.filter(
        buddy_spendings__participant_feuser=feuser,
        buddy_approved=False,
        is_buddies_settlement=True,
    ).distinct().count()
    # Admin: dummy upfront-payer expenses and dummy-creditor settlements in all projects
    admin_ids = list(
        Project.objects.filter(admin_feuser=feuser).values_list("uid", flat=True)
    )
    if admin_ids:
        count += Expense.objects.filter(
            project_id__in=admin_ids,
            is_dummy=True,
            is_buddies_settlement=False,
            buddy_approved=False,
        ).count()
        count += Expense.objects.filter(
            buddy_spendings__participant_dummy__owning_group_id__in=admin_ids,
            buddy_approved=False,
            is_buddies_settlement=True,
        ).distinct().count()
    return count


@register_badge("projects")
def _count_project_actions(feuser) -> int:
    from django.utils import timezone
    from budget.models import Expense
    from buddies.models import Project, ProjectInvite, ProjectMember
    now = timezone.now()
    # Incoming project invites
    invite_count = ProjectInvite.objects.filter(
        invitee_email=feuser.email,
        expires_at__gt=now,
    ).count()
    # Non-archived projects where feuser is a member
    member_project_ids = list(
        ProjectMember.objects.filter(feuser=feuser, group__archived=False)
        .values_list("group_id", flat=True)
    )
    if not member_project_ids:
        return invite_count
    # Expenses where feuser is recorded as upfront payer within a project
    owner_count = Expense.objects.filter(
        project_id__in=member_project_ids,
        owning_feuser=feuser,
        buddy_approved=False,
        is_buddies_settlement=False,
    ).count()
    # Settlements where feuser is the creditor within a project
    creditor_count = Expense.objects.filter(
        project_id__in=member_project_ids,
        buddy_spendings__participant_feuser=feuser,
        buddy_approved=False,
        is_buddies_settlement=True,
    ).distinct().count()
    # Admin: dummy upfront-payer expenses and dummy-creditor settlements
    admin_ids = list(
        Project.objects.filter(uid__in=member_project_ids, admin_feuser=feuser)
        .values_list("uid", flat=True)
    )
    admin_count = 0
    if admin_ids:
        admin_count += Expense.objects.filter(
            project_id__in=admin_ids,
            is_dummy=True,
            is_buddies_settlement=False,
            buddy_approved=False,
        ).count()
        admin_count += Expense.objects.filter(
            buddy_spendings__participant_dummy__owning_group_id__in=admin_ids,
            buddy_approved=False,
            is_buddies_settlement=True,
        ).distinct().count()
    return invite_count + owner_count + creditor_count + admin_count
