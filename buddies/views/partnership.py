"""
Partnership views: invite, onboarding wizard, kick, leave.
"""
import json
import logging

from comaney.json_utils import safe_json

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from buddies.models import CatalogPartnershipInvite
from buddies.services import partnership_actions
from buddies.services.partnership_actions import PartnershipError

_log = logging.getLogger(__name__)


def _name(feuser) -> str:
    parts = [feuser.first_name, feuser.last_name]
    full = " ".join(p for p in parts if p).strip()
    return full or feuser.email


# ---------------------------------------------------------------------------
# Send invite
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def send_partnership_invite(request):
    """
    POST body: {"invitee_id": <feuser pk>}
    Called from buddy profile and project member list.
    """
    from feusers.models import FeUser
    feuser = request.feuser
    if feuser.is_demo:
        return JsonResponse({"error": "Demo accounts cannot use Catalog Partnerships."}, status=403)
    try:
        invitee_id = int(json.loads(request.body)["invitee_id"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid request."}, status=400)
    invitee = FeUser.objects.filter(pk=invitee_id, is_active=True).first()
    if invitee is None:
        return JsonResponse({"error": "User not found."}, status=404)
    try:
        invite = partnership_actions.invite(feuser, invitee)
    except PartnershipError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    return JsonResponse({"ok": True, "invite_token": invite.token})


# ---------------------------------------------------------------------------
# Onboarding wizard page
# ---------------------------------------------------------------------------

@feuser_required
def onboarding_wizard(request, token):
    """
    GET: render the onboarding wizard page (opens modal automatically).
    The page provides all catalog data; the wizard state lives in localStorage.
    """
    from budget.models import Tag, Category

    feuser = request.feuser
    invite = get_object_or_404(
        CatalogPartnershipInvite,
        token=token,
        invitee_email=feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    )

    if invite.status == CatalogPartnershipInvite.STATUS_PENDING:
        invite.status = CatalogPartnershipInvite.STATUS_IN_SETUP
        invite.save(update_fields=["status"])

    master_feuser = invite.inviter
    master_tags = list(Tag.objects.filter(owning_feuser=master_feuser).values("uid", "title").order_by("title"))
    master_cats = list(Category.objects.filter(owning_feuser=master_feuser).values("uid", "title").order_by("title"))

    my_tags = list(Tag.objects.filter(owning_feuser=feuser).values("uid", "title").order_by("title"))
    my_cats = list(Category.objects.filter(owning_feuser=feuser).values("uid", "title").order_by("title"))

    master_tag_titles = {t["title"] for t in master_tags}
    master_cat_titles = {c["title"] for c in master_cats}

    # Pre-separate matched vs unmatched
    matched_tags = [t for t in my_tags if t["title"] in master_tag_titles]
    unmatched_tags = [t for t in my_tags if t["title"] not in master_tag_titles]
    matched_cats = [c for c in my_cats if c["title"] in master_cat_titles]
    unmatched_cats = [c for c in my_cats if c["title"] not in master_cat_titles]

    return render(request, "buddies/partnership_onboarding.html", {
        "invite": invite,
        "invite_token": token,
        "master_feuser": master_feuser,
        "master_name": _name(master_feuser),
        "master_tags": master_tags,
        "master_cats": master_cats,
        "matched_tags": matched_tags,
        "unmatched_tags": unmatched_tags,
        "matched_cats": matched_cats,
        "unmatched_cats": unmatched_cats,
        "master_tags_json": safe_json(master_tags),
        "master_cats_json": safe_json(master_cats),
        "matched_tags_json": safe_json(matched_tags),
        "matched_cats_json": safe_json(matched_cats),
        "unmatched_tags_json": safe_json(unmatched_tags),
        "unmatched_cats_json": safe_json(unmatched_cats),
    })


# ---------------------------------------------------------------------------
# Onboarding: AI suggestions
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def onboarding_ai_suggest_tags(request, token):
    invite = get_object_or_404(
        CatalogPartnershipInvite, token=token, invitee_email=request.feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    )
    from budget.models import Tag
    from buddies.services.partnership_ai import suggest_tag_mappings
    from budget.ai_service import AIBudgetExceededError

    master_tags = list(Tag.objects.filter(owning_feuser=invite.inviter).values_list("title", flat=True))
    my_tags = list(Tag.objects.filter(owning_feuser=request.feuser).values_list("title", flat=True))
    master_set = set(master_tags)
    unmatched = [t for t in my_tags if t not in master_set]

    if not unmatched:
        return JsonResponse({"mappings": []})

    try:
        mappings = suggest_tag_mappings(request.feuser, invite.inviter, unmatched, master_tags)
        return JsonResponse({"mappings": mappings})
    except AIBudgetExceededError as exc:
        return JsonResponse({"error": str(exc) or "AI budget exceeded."}, status=402)
    except Exception as exc:
        _log.error("onboarding_ai_suggest_tags error: %s", exc)
        return JsonResponse({"error": "AI suggestion failed. Please map manually."}, status=500)


@feuser_required
@require_POST
def onboarding_ai_suggest_cats(request, token):
    invite = get_object_or_404(
        CatalogPartnershipInvite, token=token, invitee_email=request.feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    )
    from budget.models import Category
    from buddies.services.partnership_ai import suggest_category_mappings
    from budget.ai_service import AIBudgetExceededError

    master_cats = list(Category.objects.filter(owning_feuser=invite.inviter).values_list("title", flat=True))
    my_cats = list(Category.objects.filter(owning_feuser=request.feuser).values_list("title", flat=True))
    master_set = set(master_cats)
    unmatched = [c for c in my_cats if c not in master_set]

    if not unmatched:
        return JsonResponse({"mappings": []})

    try:
        mappings = suggest_category_mappings(request.feuser, invite.inviter, unmatched, master_cats)
        return JsonResponse({"mappings": mappings})
    except AIBudgetExceededError as exc:
        return JsonResponse({"error": str(exc) or "AI budget exceeded."}, status=402)
    except Exception as exc:
        _log.error("onboarding_ai_suggest_cats error: %s", exc)
        return JsonResponse({"error": "AI suggestion failed. Please map manually."}, status=500)


# ---------------------------------------------------------------------------
# Onboarding: apply migration
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def onboarding_apply(request, token):
    """
    POST body:
    {
      "tag_mappings":  [{"source": "beer", "target": "alcohol"}, {"source": "wine", "target": null}],
      "cat_mappings":  [{"source": "Food", "target": "Groceries"}, ...]
    }
    source -> null means DROP.
    After apply, the invitee's catalog is replaced with the master's catalog and
    their expenses, recurring expenses and overlays are remapped onto it.
    """
    feuser = request.feuser
    invite = get_object_or_404(
        CatalogPartnershipInvite, token=token, invitee_email=feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    )
    try:
        data = json.loads(request.body)
        tag_mappings = data.get("tag_mappings", [])
        cat_mappings = data.get("cat_mappings", [])
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    partnership_actions.apply_onboarding(
        feuser, invite,
        tag_map={m["source"]: m["target"] for m in tag_mappings if m.get("source")},
        cat_map={m["source"]: m["target"] for m in cat_mappings if m.get("source")},
    )
    return JsonResponse({"ok": True, "redirect": "/budget/categories-tags/"})


# ---------------------------------------------------------------------------
# Decline invite
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def onboarding_decline(request, token):
    feuser = request.feuser
    invite = get_object_or_404(
        CatalogPartnershipInvite, token=token, invitee_email=feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    )
    partnership_actions.decline(feuser, invite)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Get current master catalog (for wizard refresh on re-open)
# ---------------------------------------------------------------------------

@feuser_required
def onboarding_catalog_state(request, token):
    """GET: return the current master catalog state for reconciliation."""
    from budget.models import Tag, Category
    feuser = request.feuser
    invite = get_object_or_404(
        CatalogPartnershipInvite, token=token, invitee_email=feuser.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    )
    master = invite.inviter
    return JsonResponse({
        "master_tags": list(Tag.objects.filter(owning_feuser=master).values("title").order_by("title")),
        "master_cats": list(Category.objects.filter(owning_feuser=master).values("title").order_by("title")),
    })


# ---------------------------------------------------------------------------
# Cancel a pending invite (revoked by inviter)
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def cancel_partnership_invite(request, token):
    try:
        partnership_actions.cancel_invite(request.feuser, token)
    except PartnershipError as exc:
        if exc.status == 404:
            raise Http404
        return JsonResponse({"error": str(exc)}, status=exc.status)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Kick a partner
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def kick_partner(request, feuser_id):
    from feusers.models import FeUser
    try:
        partnership_actions.kick(request.feuser, FeUser.objects.filter(pk=feuser_id).first())
    except PartnershipError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Leave partnership
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def leave_partnership(request):
    try:
        partnership_actions.leave(request.feuser)
    except PartnershipError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    return JsonResponse({"ok": True})
