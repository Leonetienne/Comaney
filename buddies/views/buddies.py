import json

from django.conf import settings
from django.contrib import messages as django_messages
from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from ..models import ContactInvite, BuddySpending, DummyMergeInvite, DummyUser
from ..services import BuddyArchiveService, BuddyLifecycleService, BuddyQueryService, _display_name
from ..services import contact_actions
from ..services.contact_actions import ContactError
from ..services.project_actions import rename_offline_member


@feuser_required
@require_POST
def rename_dummy(request, dummy_id):
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_feuser=request.feuser)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    try:
        rename_offline_member(dummy, data.get("display_name", ""))
    except ContactError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    return JsonResponse({"display_name": dummy.display_name})


@feuser_required
@require_POST
def add_dummy(request):
    name = request.POST.get("display_name", "").strip()
    if not name:
        return redirect("buddies:index")
    contact_actions.add_offline_contact(request.feuser, name)
    return redirect("buddies:index")


@feuser_required
def kick_dummy(request, dummy_id):
    """GET: confirmation page. POST: execute removal."""
    feuser = request.feuser
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_feuser=feuser)

    if dummy.is_archive:
        if BuddyArchiveService.archive_has_expenses(dummy):
            django_messages.error(
                request,
                "Achim Archive still holds expenses. Delete all archived expenses first.",
            )
        elif request.method == "POST" and request.POST.get("confirmed") == "yes":
            contact_actions.remove_offline_contact(feuser, dummy)
        return redirect("buddies:contacts")

    if request.method == "POST":
        debt_warning_accepted = request.POST.get("debt_warning_accepted") == "yes"
        result = BuddyLifecycleService.kick_dummy(
            feuser, dummy, has_debt_warning_accepted=debt_warning_accepted
        )
        if result.get("kicked"):
            url = reverse("buddies:contacts")
            if result.get("archive_created") and not feuser.has_seen_achim_intro:
                url += "?achim=new"
                feuser.has_seen_achim_intro = True
                feuser.save(update_fields=["has_seen_achim_intro"])
            return redirect(url)
        return redirect("buddies:contacts")

    # GET: build confirmation page data
    net = BuddyQueryService.get_net_debt(feuser, contact_dummy=dummy)
    from budget.models import Expense
    expense_count = (
        BuddySpending.objects.filter(participant_dummy=dummy)
        .values("expense")
        .distinct()
        .count()
        + Expense.objects.filter(
            owning_feuser=feuser, upfront_payee_dummy=dummy, is_dummy=True
        ).count()
    )
    archive_exists = DummyUser.objects.filter(owning_feuser=feuser, is_archive=True).exists()

    return render(request, "buddies/kick_dummy_confirm.html", {
        "active_nav": "contacts",
        "dummy": dummy,
        "net": net,
        "net_abs": abs(net),
        "has_balance": abs(net) > 0.005,
        "expense_count": expense_count,
        "archive_exists": archive_exists,
        "currency": feuser.currency,
    })


@feuser_required
def personal_archive_wipe(request, dummy_id):
    """GET: big-warning confirmation page. POST with confirmed=yes: wipe."""
    feuser = request.feuser
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_feuser=feuser, is_archive=True)

    if request.method == "POST" and request.POST.get("confirmed") == "yes":
        BuddyArchiveService.wipe_archive(dummy)
        django_messages.success(request, "Achim Archive has been cleared.")
        return redirect("buddies:contacts")

    user_impact = BuddyArchiveService.get_user_impact_in_personal_archive(feuser, dummy)
    participant_count, payer_count = BuddyArchiveService.get_archive_expense_counts_split(dummy)
    expense_count = participant_count + payer_count

    return render(request, "buddies/archive_wipe_confirm.html", {
        "active_nav": "contacts",
        "dummy": dummy,
        "group": None,
        "cancel_url": reverse("buddies:contacts"),
        "user_impact": user_impact,
        "user_impact_abs": abs(user_impact),
        "expense_count": expense_count,
        "participant_count": participant_count,
        "payer_count": payer_count,
        "currency": feuser.currency,
    })


@feuser_required
@require_POST
def invite_actual(request):
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("buddies:contacts")
    outcome, _obj = contact_actions.invite_by_email(request.feuser, email)
    level, text = contact_actions.invite_message(outcome, email)
    # no toast for yourself, an existing contact or an instant link
    if outcome not in ("self", "already_contacts", "link"):
        getattr(django_messages, level)(request, text)
    return redirect("buddies:contacts")


@feuser_required
@require_POST
def send_contact_invite(request):
    """
    POST body: {"invitee_id": <feuser pk>}
    Invites a specific user as a contact without typing their email.
    Called from buddy lists and project member lists.
    """
    from feusers.models import FeUser
    feuser = request.feuser
    if feuser.is_demo:
        return JsonResponse({"error": "Demo accounts cannot invite contacts."}, status=403)
    try:
        invitee_id = int(json.loads(request.body)["invitee_id"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid request."}, status=400)
    invitee = FeUser.objects.filter(pk=invitee_id, is_active=True).first()
    if invitee is None:
        return JsonResponse({"error": "User not found."}, status=404)
    try:
        contact_actions.invite_feuser(feuser, invitee)
    except ContactError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    return JsonResponse({"ok": True})


@feuser_required
def view_invite(request, token):
    try:
        invite = ContactInvite.objects.select_related("inviter").get(token=token)
    except ContactInvite.DoesNotExist:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if not invite.is_valid():
        invite.delete()
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if request.feuser.email.lower() != invite.invitee_email.lower():
        return render(request, "buddies/invite_wrong_account.html", {
            "active_nav": "buddies",
            "invite": invite,
        })

    return render(request, "buddies/invite_view.html", {
        "active_nav": "buddies",
        "invite": invite,
        "inviter_name": _display_name(invite.inviter),
    })


@feuser_required
@require_POST
def accept_invite(request, token):
    link = BuddyLifecycleService.accept_invite(token, request.feuser)
    if link is None:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})
    return redirect("buddies:index")


@feuser_required
@require_POST
def decline_invite(request, token):
    BuddyLifecycleService.decline_invite(token, request.feuser)
    return redirect("buddies:index")


@feuser_required
@require_POST
def revoke_invite(request, token):
    BuddyLifecycleService.revoke_invite(token, request.feuser)
    return redirect("buddies:index")


@feuser_required
@require_POST
def revoke_onboarding_invite(request, token):
    from ..models import BuddyOnboardingInvite
    try:
        invite = BuddyOnboardingInvite.objects.get(
            token=token,
            inviting_feuser=request.feuser,
            group__isnull=True,
        )
        invite.delete()
    except BuddyOnboardingInvite.DoesNotExist:
        pass
    return redirect("buddies:contacts")


@feuser_required
@require_POST
def kick_actual(request, link_id):
    try:
        contact_actions.remove_contact(request.feuser, contact_actions.own_link(request.feuser, link_id))
    except ContactError:
        pass
    return redirect("buddies:index")


@feuser_required
@require_POST
def set_auto_accept(request, link_id):
    """
    Toggle the current feuser's auto-accept of entries recorded by the buddy on
    the other side of this link. Enabling also accepts that buddy's pending
    entries and project invitations retroactively (see
    BuddyTrustService.set_auto_accept).
    """
    try:
        link = contact_actions.own_link(request.feuser, link_id)
    except ContactError:
        raise Http404
    enabled = request.POST.get("enabled") == "1"
    result, msg = contact_actions.set_auto_accept(request.feuser, link, enabled)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "enabled": enabled,
            "accepted_entries": result.entries,
            "joined_projects": result.projects,
            "message": msg,
        })
    django_messages.success(request, msg)
    return redirect("buddies:contacts")


@feuser_required
@require_POST
def merge_dummy(request, dummy_id):
    """Merge an offline contact into another offline contact (immediate) or
    request a merge into an already-linked contact (needs their approval)."""
    from feusers.models import FeUser

    feuser = request.feuser
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_feuser=feuser, is_archive=False)

    if feuser.is_demo:
        django_messages.error(request, "Demo accounts cannot merge contacts.")
        return redirect("buddies:contacts")

    target_key = request.POST.get("target_key", "").strip()
    if target_key == "self":
        outcome = BuddyLifecycleService.merge_dummy_into_self(feuser, dummy)
        if outcome == "already_pending":
            django_messages.error(request, f"\"{dummy.display_name}\" has a pending merge request. Revoke it first if you want to merge into yourself.")
        else:
            django_messages.success(request, f"Merged \"{dummy.display_name}\" into yourself.")
        return redirect("buddies:contacts")

    if len(target_key) < 2 or not target_key[1:].isdigit():
        return redirect("buddies:contacts")
    kind, target_id = target_key[0], int(target_key[1:])

    if kind == "d":
        target = get_object_or_404(DummyUser, uid=target_id, owning_feuser=feuser, is_archive=False)
        if target.pk == dummy.pk:
            return redirect("buddies:contacts")
        outcome = BuddyLifecycleService.merge_dummy_into_dummy_now(feuser, dummy, target)
        if outcome == "already_pending":
            django_messages.error(request, f"\"{dummy.display_name}\" has a pending merge request. Revoke it first if you want to merge into someone else.")
        else:
            django_messages.success(request, f"Merged \"{dummy.display_name}\" into {target.display_name}.")
    elif kind == "f":
        target_feuser = get_object_or_404(FeUser, pk=target_id, is_active=True)
        outcome, obj = BuddyLifecycleService.request_merge_with_feuser(feuser, dummy, target_feuser)
        if outcome == "not_linked":
            django_messages.error(request, "You can only request a merge with someone who is already one of your contacts.")
        elif outcome == "self":
            django_messages.error(request, "You cannot merge into yourself.")
        elif outcome == "already_pending":
            django_messages.error(request, f"\"{dummy.display_name}\" already has a pending merge request. Revoke it first if you want to send a new one.")
        elif outcome == "demo_restricted":
            django_messages.error(request, "Demo accounts cannot send merge requests.")
        elif outcome == "target_is_demo":
            django_messages.error(request, "Demo accounts cannot be merge targets.")
        elif outcome == "invite":
            django_messages.success(request, f"Merge request sent to {_display_name(target_feuser)}.")
    return redirect("buddies:contacts")


@feuser_required
def view_merge_invite(request, token):
    try:
        invite = DummyMergeInvite.objects.select_related(
            "inviting_feuser", "dummy__owning_group"
        ).get(token=token)
    except DummyMergeInvite.DoesNotExist:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies", "noun": "merge request"})

    if not invite.is_valid():
        invite.delete()
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies", "noun": "merge request"})

    if invite.invited_feuser_id != request.feuser.pk:
        return render(request, "buddies/invite_wrong_account.html", {
            "active_nav": "buddies",
            "invite": invite,
            "noun": "merge request",
            "invitee_display": invite.invited_feuser.email,
        })

    return render(request, "buddies/merge_view.html", {
        "active_nav": "buddies",
        "invite": invite,
        "inviting_name": _display_name(invite.inviting_feuser),
        "group": invite.dummy.owning_group,
    })


@feuser_required
@require_POST
def accept_merge(request, token):
    try:
        invite = DummyMergeInvite.objects.select_related("dummy__owning_group").get(token=token)
        project = invite.dummy.owning_group
        dummy_name = invite.dummy.display_name
    except DummyMergeInvite.DoesNotExist:
        project = None
        dummy_name = None

    ok = BuddyLifecycleService.accept_merge(token, request.feuser)
    if not ok:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies", "noun": "merge request"})

    if project:
        django_messages.success(request, f'"{dummy_name}"\'s history in "{project.name}" is now linked to your account.')
        return redirect("projects:project_detail", project_id=project.uid)
    return redirect("buddies:index")


@feuser_required
@require_POST
def decline_merge(request, token):
    project = None
    try:
        invite = DummyMergeInvite.objects.select_related("dummy__owning_group").get(
            token=token,
            invited_feuser=request.feuser,
        )
        project = invite.dummy.owning_group
        invite.delete()
    except DummyMergeInvite.DoesNotExist:
        pass
    if project:
        return redirect("projects:project_detail", project_id=project.uid)
    return redirect("buddies:index")


@feuser_required
@require_POST
def revoke_merge_invite(request, token):
    """Revoke an outgoing merge request. Works for both personal and project
    dummies; redirects back to wherever that dummy is managed."""
    try:
        invite = DummyMergeInvite.objects.select_related("dummy__owning_group").get(
            token=token, inviting_feuser=request.feuser,
        )
    except DummyMergeInvite.DoesNotExist:
        return redirect("buddies:contacts")
    project = invite.dummy.owning_group
    BuddyLifecycleService.revoke_merge_invite(token, request.feuser)
    if project:
        return redirect("projects:project_settings", project_id=project.pk)
    return redirect("buddies:contacts")


@feuser_required
def dummy_picture(request, dummy_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    feuser = request.feuser
    try:
        dummy = DummyUser.objects.select_related(
            "owning_feuser", "owning_group"
        ).get(pk=dummy_id)
    except DummyUser.DoesNotExist:
        raise Http404

    is_authorized = (
        (dummy.owning_feuser_id is not None and dummy.owning_feuser_id == feuser.pk)
        or (
            dummy.owning_group_id is not None
            and dummy.owning_group.admin_feuser_id == feuser.pk
        )
    )
    if not is_authorized:
        raise Http404

    action = request.POST.get("action")

    if action == "picture":
        upload = request.FILES.get("profile_picture")
        if not upload:
            return JsonResponse({"ok": False, "error": "No file selected."}, status=400)
        if upload.size > 5 * 1024 * 1024:
            return JsonResponse({"ok": False, "error": "File too large. Maximum is 5 MB."}, status=400)
        try:
            from PIL import Image, ImageOps
            img = Image.open(upload)
            img.verify()
            upload.seek(0)
            img = Image.open(upload)
            img = ImageOps.fit(img, (256, 256), Image.LANCZOS)
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            ppics_dir = settings.MEDIA_ROOT / "offline-buddy-ppic"
            ppics_dir.mkdir(exist_ok=True)
            img.save(ppics_dir / f"{dummy.pk}.jpg", "JPEG", quality=85)
            from django.utils import timezone as _tz
            dummy.profile_picture = True
            dummy.last_mod = _tz.now()
            dummy.save(update_fields=["profile_picture", "last_mod"])
            return JsonResponse({"ok": True})
        except Exception:
            return JsonResponse(
                {"ok": False, "error": "Could not process the image. Please upload a valid image file."},
                status=400,
            )

    elif action == "picture_delete":
        from django.utils import timezone as _tz
        ppic_path = settings.MEDIA_ROOT / "offline-buddy-ppic" / f"{dummy.pk}.jpg"
        ppic_path.unlink(missing_ok=True)
        dummy.profile_picture = False
        dummy.last_mod = _tz.now()
        dummy.save(update_fields=["profile_picture", "last_mod"])
        return JsonResponse({"ok": True})

    return JsonResponse({"ok": False, "error": "Unknown action."}, status=400)
