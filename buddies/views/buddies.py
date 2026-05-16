from django.contrib import messages as django_messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from budget.decorators import feuser_required
from ..models import BuddyInvite, BuddyLink, BuddySpending, DummyMergeInvite, DummyUser
from ..services import BuddyArchiveService, BuddyLifecycleService, BuddyQueryService, _display_name


@feuser_required
@require_POST
def add_dummy(request):
    name = request.POST.get("display_name", "").strip()
    if not name:
        return redirect("buddies:buddies_page")
    BuddyLifecycleService.add_dummy(request.feuser, name)
    return redirect("buddies:buddies_page")


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
            dummy.delete()
        return redirect("buddies:my_buddies")

    if request.method == "POST":
        debt_warning_accepted = request.POST.get("debt_warning_accepted") == "yes"
        result = BuddyLifecycleService.kick_dummy(
            feuser, dummy, has_debt_warning_accepted=debt_warning_accepted
        )
        if result.get("kicked"):
            url = reverse("buddies:my_buddies")
            if result.get("archive_created"):
                url += "?achim=new"
            return redirect(url)
        return redirect("buddies:my_buddies")

    # GET: build confirmation page data
    net = BuddyQueryService.get_net_debt(feuser, buddy_dummy=dummy)
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
        "active_nav": "my_buddies",
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
        return redirect("buddies:my_buddies")

    user_impact = BuddyArchiveService.get_user_impact_in_personal_archive(feuser, dummy)
    participant_count, payer_count = BuddyArchiveService.get_archive_expense_counts_split(dummy)
    expense_count = participant_count + payer_count

    return render(request, "buddies/archive_wipe_confirm.html", {
        "active_nav": "my_buddies",
        "dummy": dummy,
        "group": None,
        "cancel_url": reverse("buddies:my_buddies"),
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
