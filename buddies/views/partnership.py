"""
Partnership views: invite, onboarding wizard, kick, leave.
"""
import json
import logging

from django.contrib import messages as django_messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from buddies.models import (
    BuddyLink,
    CatalogPartnership,
    CatalogPartnershipInvite,
    CatalogPartnershipMembership,
    ProjectMember,
)

_log = logging.getLogger(__name__)


def _has_mutual_connection(feuser_a, feuser_b) -> bool:
    """True if the two users share a BuddyLink or at least one Project."""
    from django.db.models import Q
    if BuddyLink.objects.filter(
        Q(user_a=feuser_a, user_b=feuser_b) | Q(user_a=feuser_b, user_b=feuser_a)
    ).exists():
        return True
    a_projects = set(ProjectMember.objects.filter(feuser=feuser_a).values_list("group_id", flat=True))
    return ProjectMember.objects.filter(feuser=feuser_b, group_id__in=a_projects).exists()


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

    try:
        data = json.loads(request.body)
        invitee_id = int(data["invitee_id"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    try:
        invitee = FeUser.objects.get(pk=invitee_id, is_active=True)
    except FeUser.DoesNotExist:
        return JsonResponse({"error": "User not found."}, status=404)

    if invitee == feuser:
        return JsonResponse({"error": "Cannot invite yourself."}, status=400)

    if not _has_mutual_connection(feuser, invitee):
        return JsonResponse({"error": "No mutual connection with this user."}, status=403)

    # Check invitee not already in a partnership
    if hasattr(invitee, "catalog_membership"):
        return JsonResponse({"error": "This user is already in a Catalog Partnership."}, status=409)

    # Check no pending invite already
    if CatalogPartnershipInvite.objects.filter(
        invitee_email=invitee.email,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    ).exists():
        return JsonResponse({"error": "An invite is already pending for this user."}, status=409)

    # Create or reuse the inviter's partnership
    try:
        membership = feuser.catalog_membership
        partnership = membership.partnership
    except CatalogPartnershipMembership.DoesNotExist:
        partnership = CatalogPartnership.objects.create()
        CatalogPartnershipMembership.objects.create(
            partnership=partnership,
            feuser=feuser,
            onboarding_complete=True,
        )

    invite = CatalogPartnershipInvite.objects.create(
        partnership=partnership,
        inviter=feuser,
        invitee_email=invitee.email,
    )

    from buddies.services.partnership_email import notify_partner_event
    notify_partner_event(invitee, "invite_sent", invite=invite)

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
        "master_tags_json": json.dumps(master_tags),
        "master_cats_json": json.dumps(master_cats),
        "matched_tags_json": json.dumps(matched_tags),
        "matched_cats_json": json.dumps(matched_cats),
        "unmatched_tags_json": json.dumps(unmatched_tags),
        "unmatched_cats_json": json.dumps(unmatched_cats),
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
    from budget.express_service import AIBudgetExceededError

    master_tags = list(Tag.objects.filter(owning_feuser=invite.inviter).values_list("title", flat=True))
    my_tags = list(Tag.objects.filter(owning_feuser=request.feuser).values_list("title", flat=True))
    master_set = set(master_tags)
    unmatched = [t for t in my_tags if t not in master_set]

    if not unmatched:
        return JsonResponse({"mappings": []})

    try:
        mappings = suggest_tag_mappings(request.feuser, unmatched, master_tags)
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
    from budget.express_service import AIBudgetExceededError

    master_cats = list(Category.objects.filter(owning_feuser=invite.inviter).values_list("title", flat=True))
    my_cats = list(Category.objects.filter(owning_feuser=request.feuser).values_list("title", flat=True))
    master_set = set(master_cats)
    unmatched = [c for c in my_cats if c not in master_set]

    if not unmatched:
        return JsonResponse({"mappings": []})

    try:
        mappings = suggest_category_mappings(request.feuser, unmatched, master_cats)
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
    After apply, the invitee's catalog is replaced with the master's catalog.
    """
    from django.db import transaction
    from budget.models import Tag, Category, Expense

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

    master = invite.inviter

    with transaction.atomic():
        # --- Rewrite expense tags ---
        tag_map = {m["source"]: m["target"] for m in tag_mappings if m.get("source")}
        master_tag_objs = {t.title: t for t in Tag.objects.filter(owning_feuser=master)}

        # Fetch all my tags once
        my_tag_objs = {t.title: t for t in Tag.objects.filter(owning_feuser=feuser)}

        # For each expense, rewrite tags
        my_expenses = list(
            Expense.objects.filter(owning_feuser=feuser).prefetch_related("tags")
        )
        for expense in my_expenses:
            current_tag_titles = [t.title for t in expense.tags.all()]
            new_tags = []
            changed = False
            for title in current_tag_titles:
                if title in master_tag_objs:
                    # already matches master - keep as-is (we'll replace with master's obj later)
                    new_tags.append(title)
                elif title in tag_map:
                    target = tag_map[title]
                    if target and target in master_tag_objs:
                        new_tags.append(target)
                        changed = True
                    else:
                        changed = True  # drop it
                # else: no mapping provided, drop it
                else:
                    changed = True

            if changed:
                tag_objs_new = [
                    master_tag_objs[t] for t in new_tags if t in master_tag_objs
                ]
                expense.tags.set(tag_objs_new)

        # --- Rewrite expense categories ---
        cat_map = {m["source"]: m["target"] for m in cat_mappings if m.get("source")}
        master_cat_objs = {c.title: c for c in Category.objects.filter(owning_feuser=master)}

        for expense in my_expenses:
            if expense.category_id:
                # get current category title
                try:
                    cur_cat_title = Category.objects.get(pk=expense.category_id).title
                except Category.DoesNotExist:
                    cur_cat_title = None
                if cur_cat_title:
                    if cur_cat_title in master_cat_objs:
                        pass  # already matches master title, we'll re-point below
                    elif cur_cat_title in cat_map:
                        target = cat_map[cur_cat_title]
                        if target and target in master_cat_objs:
                            expense.category = master_cat_objs[target]
                        else:
                            expense.category = None
                        expense.save(update_fields=["category"])
                    else:
                        # no mapping - drop
                        expense.category = None
                        expense.save(update_fields=["category"])

        # Delete all of the invitee's tags and categories
        Tag.objects.filter(owning_feuser=feuser).delete()
        Category.objects.filter(owning_feuser=feuser).delete()

        # Copy master's full catalog to invitee
        for tag in Tag.objects.filter(owning_feuser=master):
            Tag.objects.create(owning_feuser=feuser, title=tag.title)
        for cat in Category.objects.filter(owning_feuser=master):
            Category.objects.create(owning_feuser=feuser, title=cat.title)

        # Re-point expense tags to new tag objects (now owned by feuser)
        new_my_tag_objs = {t.title: t for t in Tag.objects.filter(owning_feuser=feuser)}
        new_my_cat_objs = {c.title: c for c in Category.objects.filter(owning_feuser=feuser)}

        # Fix tag references on expenses (they were pointing to master's tag objects)
        for expense in my_expenses:
            current_tags = list(expense.tags.all())
            if current_tags:
                new_tag_list = [
                    new_my_tag_objs[t.title]
                    for t in current_tags
                    if t.title in new_my_tag_objs
                ]
                expense.tags.set(new_tag_list)
            # Fix category reference
            if expense.category_id:
                try:
                    cur_cat = Category.objects.get(pk=expense.category_id)
                    if cur_cat.owning_feuser_id == master.pk and cur_cat.title in new_my_cat_objs:
                        expense.category = new_my_cat_objs[cur_cat.title]
                        expense.save(update_fields=["category"])
                except Category.DoesNotExist:
                    pass

        # Mark invite as accepted and add membership
        invite.status = CatalogPartnershipInvite.STATUS_ACTIVE
        invite.save(update_fields=["status"])

        membership, _ = CatalogPartnershipMembership.objects.get_or_create(
            feuser=feuser,
            defaults={"partnership": invite.partnership, "onboarding_complete": False},
        )
        membership.partnership = invite.partnership
        membership.onboarding_complete = True
        membership.save(update_fields=["partnership", "onboarding_complete"])

    # Notifications
    from buddies.services.partnership_email import notify_partner_event
    notify_partner_event(invite.inviter, "invite_accepted", invitee=feuser)
    existing_partners = list(
        invite.partnership.memberships
        .exclude(feuser=feuser)
        .exclude(feuser=invite.inviter)
        .select_related("feuser")
    )
    for m in existing_partners:
        notify_partner_event(m.feuser, "new_partner_joined", joined=feuser)

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
    invite.status = CatalogPartnershipInvite.STATUS_DECLINED
    invite.save(update_fields=["status"])

    from buddies.services.partnership_email import notify_partner_event
    notify_partner_event(invite.inviter, "invite_declined", invitee=feuser)

    # Dissolve partnership if no remaining members besides inviter
    partnership = invite.partnership
    from buddies.services.partnership import dissolve_if_solo
    dissolve_if_solo(partnership)

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
    actor = request.feuser
    try:
        membership = actor.catalog_membership
    except CatalogPartnershipMembership.DoesNotExist:
        return JsonResponse({"error": "You are not in a partnership."}, status=403)

    invite = get_object_or_404(
        CatalogPartnershipInvite,
        token=token,
        partnership=membership.partnership,
        status__in=[CatalogPartnershipInvite.STATUS_PENDING, CatalogPartnershipInvite.STATUS_IN_SETUP],
    )
    invite.status = CatalogPartnershipInvite.STATUS_DECLINED
    invite.save(update_fields=["status"])
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Kick a partner
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def kick_partner(request, feuser_id):
    from feusers.models import FeUser
    actor = request.feuser

    try:
        membership = actor.catalog_membership
    except CatalogPartnershipMembership.DoesNotExist:
        return JsonResponse({"error": "You are not in a partnership."}, status=403)

    try:
        target = FeUser.objects.get(pk=feuser_id)
        target_membership = target.catalog_membership
    except (FeUser.DoesNotExist, CatalogPartnershipMembership.DoesNotExist):
        return JsonResponse({"error": "Partner not found."}, status=404)

    if target_membership.partnership_id != membership.partnership_id:
        return JsonResponse({"error": "Not in the same partnership."}, status=403)

    if target == actor:
        return JsonResponse({"error": "Use 'leave' to remove yourself."}, status=400)

    from buddies.services.partnership import remove_member
    remove_member(target, reason="kicked")
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Leave partnership
# ---------------------------------------------------------------------------

@feuser_required
@require_POST
def leave_partnership(request):
    feuser = request.feuser
    try:
        feuser.catalog_membership
    except CatalogPartnershipMembership.DoesNotExist:
        return JsonResponse({"error": "You are not in a partnership."}, status=403)

    from buddies.services.partnership import remove_member
    remove_member(feuser, reason="left")
    return JsonResponse({"ok": True})
