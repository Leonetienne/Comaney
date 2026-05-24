import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

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


@feuser_required
@require_POST
def category_create(request):
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    if len(title) > 128:
        return JsonResponse({"error": "Title must be 128 characters or fewer."}, status=400)
    category = Category.objects.create(owning_feuser=request.feuser, title=title)
    from buddies.services.partnership import sync_category_create
    sync_category_create(title, request.feuser)
    return JsonResponse({"uid": category.uid, "title": category.title})


@feuser_required
@require_POST
def category_delete(request, uid):
    category = get_object_or_404(Category, uid=uid, owning_feuser=request.feuser)
    title = category.title
    category.delete()
    from buddies.services.partnership import sync_category_delete
    sync_category_delete(title, request.feuser)
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def category_rename(request, uid):
    category = get_object_or_404(Category, uid=uid, owning_feuser=request.feuser)
    old_title = category.title
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    if len(title) > 128:
        return JsonResponse({"error": "Title must be 128 characters or fewer."}, status=400)
    category.title = title
    category.last_mod = timezone.now()
    category.save(update_fields=["title", "last_mod"])
    from buddies.services.partnership import sync_category_rename
    sync_category_rename(old_title, title, request.feuser)
    return JsonResponse({"uid": category.uid, "title": category.title})


@feuser_required
@require_POST
def tag_create(request):
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    if len(title) > 128:
        return JsonResponse({"error": "Title must be 128 characters or fewer."}, status=400)
    tag = Tag.objects.create(owning_feuser=request.feuser, title=title)
    from buddies.services.partnership import sync_tag_create
    sync_tag_create(title, request.feuser)
    return JsonResponse({"uid": tag.uid, "title": tag.title})


@feuser_required
@require_POST
def tag_delete(request, uid):
    tag = get_object_or_404(Tag, uid=uid, owning_feuser=request.feuser)
    title = tag.title
    tag.delete()
    from buddies.services.partnership import sync_tag_delete
    sync_tag_delete(title, request.feuser)
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def tag_rename(request, uid):
    tag = get_object_or_404(Tag, uid=uid, owning_feuser=request.feuser)
    old_title = tag.title
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    if len(title) > 128:
        return JsonResponse({"error": "Title must be 128 characters or fewer."}, status=400)
    tag.title = title
    tag.last_mod = timezone.now()
    tag.save(update_fields=["title", "last_mod"])
    from buddies.services.partnership import sync_tag_rename
    sync_tag_rename(old_title, title, request.feuser)
    return JsonResponse({"uid": tag.uid, "title": tag.title})
