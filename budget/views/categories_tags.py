import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .. import catalog_service
from ..catalog_service import CatalogError
from ..decorators import feuser_required
from ..models import Category, Tag


def _partnership_context(feuser):
    """Return context keys for the catalog page partnership UI."""
    from buddies.models import CatalogPartnershipMembership, CatalogPartnershipInvite
    from feusers.models import FeUser

    try:
        membership = feuser.catalog_membership
        partnership = membership.partnership
        partner_memberships = list(
            partnership.memberships
            .exclude(feuser=feuser)
            .select_related("feuser")
            .order_by("joined_at")
        )

        # Pending invites (not yet accepted) — resolve invitee feuser objects
        raw_invites = list(
            partnership.invites.filter(
                status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
            ).order_by("created_at")
        )
        invitee_map = {
            u.email: u
            for u in FeUser.objects.filter(
                email__in=[i.invitee_email for i in raw_invites], is_active=True
            )
        }
        pending_invites = [
            {"invite": inv, "feuser": invitee_map[inv.invitee_email]}
            for inv in raw_invites
            if inv.invitee_email in invitee_map
        ]

        return {
            "partnership": partnership,
            "partnership_membership": membership,
            "partner_memberships": partner_memberships,
            "pending_invites": pending_invites,
            "has_active_partnership": membership.onboarding_complete,
            "has_pending_onboarding": not membership.onboarding_complete,
        }
    except CatalogPartnershipMembership.DoesNotExist:
        pass

    pending_invite = CatalogPartnershipInvite.objects.filter(
        invitee_email=feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    ).select_related("inviter").first()
    return {
        "partnership": None,
        "partnership_membership": None,
        "partner_memberships": [],
        "pending_invites": [],
        "has_active_partnership": False,
        "has_pending_onboarding": False,
        "pending_partnership_invite": pending_invite,
    }


@feuser_required
def categories_tags(request):
    feuser = request.feuser
    categories = Category.objects.filter(owning_feuser=feuser)
    tags = Tag.objects.filter(owning_feuser=feuser)
    ctx = {
        "active_nav": "categories_tags",
        "categories": categories,
        "tags": tags,
    }
    ctx.update(_partnership_context(feuser))
    return render(request, "budget/categories_tags.html", ctx)


def _catalog_json(fn):
    try:
        item = fn()
    except CatalogError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"uid": item.uid, "title": item.title})


@feuser_required
@require_POST
def category_create(request):
    title = json.loads(request.body).get("title", "")
    return _catalog_json(lambda: catalog_service.create_category(request.feuser, title))


@feuser_required
@require_POST
def category_delete(request, uid):
    catalog_service.delete_category(get_object_or_404(Category, uid=uid, owning_feuser=request.feuser), request.feuser)
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def category_rename(request, uid):
    category = get_object_or_404(Category, uid=uid, owning_feuser=request.feuser)
    title = json.loads(request.body).get("title", "")
    return _catalog_json(lambda: catalog_service.rename_category(category, request.feuser, title))


@feuser_required
@require_POST
def tag_create(request):
    title = json.loads(request.body).get("title", "")
    return _catalog_json(lambda: catalog_service.create_tag(request.feuser, title))


@feuser_required
@require_POST
def tag_delete(request, uid):
    catalog_service.delete_tag(get_object_or_404(Tag, uid=uid, owning_feuser=request.feuser), request.feuser)
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def tag_rename(request, uid):
    tag = get_object_or_404(Tag, uid=uid, owning_feuser=request.feuser)
    title = json.loads(request.body).get("title", "")
    return _catalog_json(lambda: catalog_service.rename_tag(tag, request.feuser, title))
