import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages as django_messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from feusers.models import FeUser
from ..models import BuddyGroup, BuddyGroupInvite, BuddyGroupMember, BuddySpending, DummyUser
from ..services import BuddyArchiveService, BuddyGroupService, _display_name


@feuser_required
@require_POST
def create_group(request):
    name = request.POST.get("name", "").strip()
    if not name:
        return redirect("buddies:my_buddies")
    group = BuddyGroupService.create_group(request.feuser, name)
    return redirect("projects:project_detail", project_id=group.uid)


@feuser_required
@require_POST
def group_invite_member(request, group_id):
    from django.conf import settings as django_settings
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("projects:project_detail", project_id=group_id)

    outcome, obj = BuddyGroupService.invite_member(group, feuser, email)
    if outcome == "demo_restricted":
        django_messages.error(request, "Demo accounts cannot invite group members.")
    elif outcome == "invitee_is_demo":
        django_messages.error(request, "That email address is not available.")
    elif outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "self":
        django_messages.error(request, "You cannot invite yourself.")
    elif outcome == "already_member":
        django_messages.info(request, f"{email} is already a member of this group.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated. Share this registration link: {site_url}/register/")
    elif outcome == "onboarding":
        django_messages.success(request, f"A registration and group invitation has been sent to {email}.")
    elif outcome == "invite":
        django_messages.success(request, f"Group invitation sent to {email}.")
    elif outcome == "member":
        django_messages.success(request, f"{email} has been added to the group.")
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
@require_POST
def group_revoke_invite(request, group_id, token):
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=request.feuser)
    BuddyGroupService.revoke_group_invite(token, request.feuser)
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
def group_remove_member(request, group_id, member_id):
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    member = get_object_or_404(BuddyGroupMember, uid=member_id, group=group)

    if member.feuser_id == feuser.pk:
        django_messages.error(request, "You cannot remove yourself. Transfer admin rights first or dissolve the group.")
        return redirect("projects:project_detail", project_id=group_id)

    if member.dummy_id:
        dummy = member.dummy

        if dummy.is_archive:
            # Archive removal only allowed when empty; enforced here and in template
            if BuddyArchiveService.archive_has_expenses(dummy):
                django_messages.error(request, "Achim Archive still holds expenses. Delete all archived expenses first.")
                return redirect("projects:project_detail", project_id=group_id)
            if request.method == "POST" and request.POST.get("confirmed") == "yes":
                dummy.delete()
            return redirect("projects:project_detail", project_id=group_id)

        if request.method == "POST" and request.POST.get("confirmed") == "yes":
            archive_created = BuddyGroupService.delete_group_dummy(group, feuser, dummy)
            url = reverse("projects:project_detail", kwargs={"project_id": group_id})
            if archive_created and not feuser.has_seen_achim_intro:
                url += "?achim=new"
                feuser.has_seen_achim_intro = True
                feuser.save(update_fields=["has_seen_achim_intro"])
            return redirect(url)

        # GET: show rich confirmation page
        from budget.models import Expense
        net = BuddyArchiveService.get_group_dummy_balance(dummy, group)
        expense_count = (
            BuddySpending.objects.filter(participant_dummy=dummy).values("expense").distinct().count()
            + Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True).count()
        )
        archive_exists = DummyUser.objects.filter(owning_group=group, is_archive=True).exists()

        return render(request, "buddies/group_remove_dummy_confirm.html", {
            "active_nav": "my_buddies",
            "group": group,
            "member": member,
            "dummy": dummy,
            "net": net,
            "net_abs": abs(net),
            "has_balance": abs(net) > Decimal("0.005"),
            "expense_count": expense_count,
            "archive_exists": archive_exists,
            "currency": feuser.currency,
        })

    # Real feuser removal: require POST (confirm-form JS dialog in template handles UX)
    if request.method != "POST":
        return redirect("projects:project_detail", project_id=group_id)

    BuddyGroupService.remove_member(group, feuser, member)
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
def group_archive_wipe(request, group_id, dummy_id):
    """GET: big-warning page. POST with confirmed=yes: wipe all archive expenses."""
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_group=group, is_archive=True)

    if request.method == "POST" and request.POST.get("confirmed") == "yes":
        BuddyArchiveService.wipe_archive(dummy)
        django_messages.success(request, "Achim Archive has been cleared.")
        return redirect("projects:project_detail", project_id=group_id)

    user_impact = BuddyArchiveService.get_user_impact_in_group_archive(feuser, dummy, group)
    participant_count, payer_count = BuddyArchiveService.get_archive_expense_counts_split(dummy)
    expense_count = participant_count + payer_count

    return render(request, "buddies/archive_wipe_confirm.html", {
        "active_nav": "my_buddies",
        "dummy": dummy,
        "group": group,
        "cancel_url": reverse("projects:project_detail", kwargs={"project_id": group_id}),
        "user_impact": user_impact,
        "user_impact_abs": abs(user_impact),
        "expense_count": expense_count,
        "participant_count": participant_count,
        "payer_count": payer_count,
        "currency": feuser.currency,
    })


@feuser_required
@require_POST
def group_rename_dummy(request, group_id, dummy_id):
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_group=group)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    name = data.get("display_name", "").strip()
    if not name:
        return JsonResponse({"error": "Name required."}, status=400)
    if len(name) > 128:
        return JsonResponse({"error": "Name must be 128 characters or fewer."}, status=400)
    if dummy.is_archive:
        return JsonResponse({"error": "Cannot rename the archive."}, status=400)
    dummy.display_name = name
    dummy.save(update_fields=["display_name"])
    return JsonResponse({"display_name": dummy.display_name})


@feuser_required
@require_POST
def group_add_dummy(request, group_id):
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    name = request.POST.get("display_name", "").strip()
    if name:
        BuddyGroupService.create_group_dummy(group, feuser, name)
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
@require_POST
def group_send_merge(request, group_id, dummy_id):
    from django.conf import settings as django_settings
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_group=group)
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("projects:project_detail", project_id=group_id)
    outcome, obj = BuddyGroupService.send_group_dummy_merge_invite(group, feuser, dummy, email)
    if outcome == "demo_restricted":
        django_messages.error(request, "Demo accounts cannot send invitations.")
    elif outcome == "invitee_is_demo":
        django_messages.error(request, "That email address is not available.")
    elif outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated. Share this link: {site_url}/register/")
    elif outcome in ("onboarding", "invite"):
        django_messages.success(request, f"Merge invitation sent to {email}.")
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
@require_POST
def group_transfer_admin(request, group_id):
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    try:
        new_admin_id = int(request.POST.get("new_admin_id", 0))
        new_admin = FeUser.objects.get(pk=new_admin_id, is_active=True)
    except (ValueError, FeUser.DoesNotExist):
        django_messages.error(request, "Invalid user selection.")
        return redirect("projects:project_detail", project_id=group_id)
    ok = BuddyGroupService.transfer_admin(group, feuser, new_admin)
    if not ok:
        django_messages.error(request, "That user is not a group member.")
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
@require_POST
def group_leave(request, group_id):
    feuser = request.feuser
    group = get_object_or_404(
        BuddyGroup.objects.prefetch_related("members"),
        uid=group_id,
        members__feuser=feuser,
    )
    if group.admin_feuser_id == feuser.pk:
        django_messages.error(request, "You are the group admin. Transfer admin rights to another member before leaving.")
        return redirect("projects:project_detail", project_id=group_id)
    try:
        member = BuddyGroupMember.objects.get(group=group, feuser=feuser)
    except BuddyGroupMember.DoesNotExist:
        return redirect("buddies:my_buddies")
    BuddyGroupService.remove_member(group, group.admin_feuser, member, notify=False)
    django_messages.success(request, f'You have left the group "{group.name}".')
    return redirect("buddies:my_buddies")


@feuser_required
@require_POST
def group_dissolve(request, group_id):
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    confirmed = request.POST.get("confirmed") == "yes"
    if not confirmed:
        return render(request, "buddies/group_dissolve_confirm.html", {
            "active_nav": "my_buddies",
            "group": group,
        })
    BuddyGroupService.dissolve_group(group, feuser)
    django_messages.success(request, f'Group "{group.name}" has been dissolved.')
    return redirect("buddies:my_buddies")


@feuser_required
def view_group_invite(request, token):
    try:
        invite = BuddyGroupInvite.objects.select_related(
            "group", "inviting_feuser"
        ).get(token=token)
    except BuddyGroupInvite.DoesNotExist:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if not invite.is_valid():
        invite.delete()
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if request.feuser.email.lower() != invite.invitee_email.lower():
        return render(request, "buddies/invite_wrong_account.html", {
            "active_nav": "buddies",
            "invite": invite,
        })

    return render(request, "buddies/group_invite_view.html", {
        "active_nav": "buddies",
        "invite": invite,
        "inviter_name": _display_name(invite.inviting_feuser),
    })


@feuser_required
@require_POST
def accept_group_invite(request, token):
    group = BuddyGroupService.accept_group_invite(token, request.feuser)
    if group is None:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})
    django_messages.success(request, f'You joined the group "{group.name}".')
    return redirect("projects:project_detail", project_id=group.uid)


@feuser_required
@require_POST
def decline_group_invite(request, token):
    BuddyGroupService.decline_group_invite(token, request.feuser)
    return redirect("buddies:my_buddies")


@feuser_required
@require_POST
def group_rename(request, group_id):
    feuser = request.feuser
    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=feuser)
    name = request.POST.get("name", "").strip()
    if not name:
        django_messages.error(request, "Group name cannot be empty.")
        return redirect("projects:project_detail", project_id=group_id)
    if len(name) > 128:
        django_messages.error(request, "Group name must be 128 characters or fewer.")
        return redirect("projects:project_detail", project_id=group_id)
    description = request.POST.get("description", "").strip()
    group.name = name
    group.description = description
    group.save(update_fields=["name", "description"])
    return redirect("projects:project_detail", project_id=group_id)


@feuser_required
def group_picture(request, group_id):
    from PIL import Image
    import io

    group = get_object_or_404(BuddyGroup, uid=group_id, admin_feuser=request.feuser)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete":
            pic_path = settings.MEDIA_ROOT / "bgpics" / f"{group.pk}.webp"
            pic_path.unlink(missing_ok=True)
            group.group_picture = False
            group.save(update_fields=["group_picture"])
        else:
            upload = request.FILES.get("group_picture")
            if upload:
                try:
                    img = Image.open(upload)
                    img = img.convert("RGB")
                    img.thumbnail((1200, 600), Image.LANCZOS)
                    bgpics_dir = settings.MEDIA_ROOT / "bgpics"
                    bgpics_dir.mkdir(exist_ok=True)
                    buf = io.BytesIO()
                    img.save(buf, "WEBP", quality=82)
                    (bgpics_dir / f"{group.pk}.webp").write_bytes(buf.getvalue())
                    group.group_picture = True
                    group.save(update_fields=["group_picture"])
                except Exception:
                    django_messages.error(request, "Could not process the image.")

    return redirect("projects:project_detail", project_id=group.uid)
