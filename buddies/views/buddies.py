from django.contrib import messages as django_messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from ..models import BuddyInvite, BuddyLink, DummyMergeInvite, DummyUser
from ..services import BuddyLifecycleService, _display_name


@feuser_required
@require_POST
def add_dummy(request):
    name = request.POST.get("display_name", "").strip()
    if not name:
        return redirect("buddies:buddies_page")
    BuddyLifecycleService.add_dummy(request.feuser, name)
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def kick_dummy(request, dummy_id):
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_feuser=request.feuser)
    BuddyLifecycleService.kick_dummy(request.feuser, dummy, has_debt_warning_accepted=True)
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def invite_actual(request):
    from django.conf import settings as django_settings
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("buddies:my_buddies")

    outcome, obj = BuddyLifecycleService.invite_actual(request.feuser, email)
    if outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated for this instance. Give this link to your friend: {site_url}/register/")
    elif outcome == "onboarding":
        django_messages.success(request, f"A registration invitation has been sent to {email}. They will be linked as your buddy once they sign up.")
    return redirect("buddies:my_buddies")


@feuser_required
def view_invite(request, token):
    try:
        invite = BuddyInvite.objects.select_related("inviter").get(token=token)
    except BuddyInvite.DoesNotExist:
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
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def decline_invite(request, token):
    BuddyLifecycleService.decline_invite(token, request.feuser)
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def revoke_invite(request, token):
    BuddyLifecycleService.revoke_invite(token, request.feuser)
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def kick_actual(request, link_id):
    link = get_object_or_404(BuddyLink, uid=link_id)
    if link.user_a_id != request.feuser.pk and link.user_b_id != request.feuser.pk:
        return redirect("buddies:buddies_page")

    other = link.other(request.feuser)
    BuddyLifecycleService.kick_actual(request.feuser, other, has_debt_warning_accepted=True)
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def send_merge_invite(request, dummy_id):
    from django.conf import settings as django_settings
    dummy = get_object_or_404(DummyUser, uid=dummy_id, owning_feuser=request.feuser)
    email = request.POST.get("email", "").strip()
    if not email:
        return redirect("buddies:my_buddies")
    outcome, obj = BuddyLifecycleService.send_merge_invite(request.feuser, dummy, email)
    if outcome == "registration_disabled":
        django_messages.error(request, "That email address is not registered and registration is not enabled on this instance.")
    elif outcome == "onboarding_no_email":
        site_url = getattr(django_settings, "SITE_URL", "")
        django_messages.info(request, f"Emailing is deactivated for this instance. Give this link to your friend: {site_url}/register/")
    elif outcome == "onboarding":
        django_messages.success(request, f"A registration invitation has been sent to {email}. They will be linked once they sign up.")
    return redirect("buddies:my_buddies")


@feuser_required
def view_merge_invite(request, token):
    try:
        invite = DummyMergeInvite.objects.select_related(
            "inviting_feuser", "dummy__owning_group"
        ).get(token=token)
    except DummyMergeInvite.DoesNotExist:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if not invite.is_valid():
        invite.delete()
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})

    if invite.invited_feuser_id != request.feuser.pk:
        return render(request, "buddies/invite_wrong_account.html", {
            "active_nav": "buddies",
            "invite": invite,
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
    ok = BuddyLifecycleService.accept_merge(token, request.feuser)
    if not ok:
        return render(request, "buddies/invite_invalid.html", {"active_nav": "buddies"})
    return redirect("buddies:buddies_page")


@feuser_required
@require_POST
def decline_merge(request, token):
    try:
        invite = DummyMergeInvite.objects.get(
            token=token,
            invited_feuser=request.feuser,
        )
        invite.delete()
    except DummyMergeInvite.DoesNotExist:
        pass
    return redirect("buddies:buddies_page")
