import csv
import json
import urllib.parse
from datetime import date

from django.contrib import messages
from django.utils.safestring import mark_safe
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from feusers.templatetags.feuser_tags import avatar_color as _avatar_color

from ..date_utils import financial_month_range, financial_year_range
from ..decorators import feuser_required
from ..forms import ExpenseForm, ExpenseOverlayForm
from ..models import Expense, ExpenseDataOverlay, TransactionType
from ..notifications import send_settled_notification, set_initial_notification_class
from ._period import _get_month, _get_period_mode, _get_year, _month_nav_context, _year_nav_context
from ._sharing import has_buddy_or_multiuser_project


# ---------------------------------------------------------------------------
# Buddy payment helpers
# ---------------------------------------------------------------------------

def _apply_solo_spendings(expense, buddy, creator_feuser):
    """For solo projects, if buddy spendings are empty, auto-create a 100% row for the creator."""
    if buddy and buddy["mode"] == "group" and not buddy["spendings"] and buddy.get("group"):
        project = buddy["group"]
        feuser_count = project.members.filter(feuser__isnull=False).count()
        dummy_count = project.members.filter(dummy__isnull=False).count()
        if feuser_count == 1 and dummy_count == 0:
            from buddies.models import BuddySpending
            BuddySpending.objects.filter(expense=expense).delete()
            BuddySpending.objects.create(
                expense=expense,
                participant_feuser=creator_feuser,
                share_percent=100,
            )


def _buddy_context(feuser) -> dict:
    from buddies.services import BuddyQueryService
    actual = list(BuddyQueryService.get_actual_buddies(feuser))
    dummy = list(BuddyQueryService.get_dummy_buddies(feuser))
    single_buddies = [
        *[{"type": "feuser", "id": b.pk, "name": f"{b.first_name} {b.last_name}".strip() or b.email, "email": b.email,
           "ppicUrl": b.ppic_url if b.profile_picture else "", "initials": b.initials, "avatarColor": _avatar_color(b.initials)} for b in actual],
        *[{"type": "dummy", "id": d.uid, "name": d.display_name + " (offline member)",
           "ppicUrl": d.ppic_url if d.profile_picture else "", "initials": d.initials, "avatarColor": _avatar_color(d.initials)} for d in dummy],
    ]
    # Only active (non-archived) projects appear in the expense form dropdown
    projects = BuddyQueryService.get_active_projects_for_feuser(feuser)
    return {
        "buddy_actual": actual,
        "buddy_dummy": dummy,
        "buddy_groups": projects,
        "projects_data_json": json.dumps(
            BuddyQueryService.projects_data_for_expense_form(feuser)
        ),
        "single_buddies_json": json.dumps(single_buddies),
    }


def _parse_buddy_post(post, feuser):
    """
    Parse buddy payment fields from a POST request.
    Returns None if buddy_payment is not set, else a dict with keys:
      mode ('single'|'group'), upfront_type ('me'|'feuser'|'dummy'),
      upfront_feuser, upfront_dummy, group, spendings, valid.
    Single mode: max 1 participant enforced.
    """
    if not post.get("buddy_payment"):
        return None

    from buddies.models import Project, DummyUser
    from feusers.models import FeUser as FU

    mode = post.get("buddy_mode", "single")
    upfront_type = post.get("buddy_upfront_type", "me")
    result = {
        "mode": mode,
        "upfront_type": upfront_type,
        "upfront_feuser": None,
        "upfront_dummy": None,
        "group": None,
        "valid": True,
    }

    if upfront_type == "feuser":
        try:
            uid = int(post.get("buddy_upfront_id", 0))
            result["upfront_feuser"] = FU.objects.get(pk=uid, is_active=True)
        except (ValueError, FU.DoesNotExist):
            result["valid"] = False
    elif upfront_type == "dummy":
        try:
            uid = int(post.get("buddy_upfront_id", 0))
            result["upfront_dummy"] = DummyUser.objects.get(pk=uid)
        except (ValueError, DummyUser.DoesNotExist):
            result["valid"] = False

    if mode == "group":
        try:
            group_id = int(post.get("project_id", 0))
            result["group"] = Project.objects.get(
                uid=group_id,
                members__feuser=feuser,
                archived=False,
            )
        except (ValueError, Project.DoesNotExist):
            result["valid"] = False

    try:
        result["spendings"] = json.loads(post.get("buddy_spendings_json", "[]"))
    except (json.JSONDecodeError, ValueError):
        result["spendings"] = []

    # Solo project: allow empty spendings (will be auto-filled with 100% for creator)
    is_solo_project = (mode == "group" and result["group"] and
                       result["group"].members.filter(feuser__isnull=False).count() == 1 and
                       not result["group"].members.filter(dummy__isnull=False).exists())
    # Any project expense may have zero participants (payer covers the cost alone).
    is_project_expense = mode == "group" and bool(result.get("group"))
    if not result["spendings"] and not is_solo_project and not is_project_expense:
        result["valid"] = False

    # Single-buddy mode: enforce max 1 participant
    if mode == "single" and len(result["spendings"]) > 1:
        result["valid"] = False

    return result


def _existing_buddy_json(expense) -> str:
    """Serialise existing BuddySpending rows for a JS-editable expense form."""
    rows = []
    for bs in expense.buddy_spendings.select_related("participant_feuser", "participant_dummy").all():
        if bs.participant_feuser_id:
            rows.append({"type": "feuser", "id": bs.participant_feuser_id, "share_percent": float(bs.share_percent)})
        else:
            rows.append({"type": "dummy", "id": bs.participant_dummy_id, "share_percent": float(bs.share_percent)})
    return json.dumps(rows)


def _safe_back_url(url):
    """Validate that a back-URL is a relative path (prevents open redirect)."""
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme or parsed.netloc:
        return None
    if not parsed.path.startswith("/"):
        return None
    return url


@feuser_required
def expenses_list(request):
    feuser = request.feuser
    mode = _get_period_mode(request)

    if mode == "year":
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _year_nav_context(year, feuser.month_start_day, feuser.month_start_prev)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _month_nav_context(year, month, feuser.month_start_day, feuser.month_start_prev)

    ctx = {
        "active_nav": "expenses",
        "nav_show_sharing_toggle": has_buddy_or_multiuser_project(feuser),
    }
    ctx.update(nav_ctx)
    return render(request, "budget/expenses_list.html", ctx)


@feuser_required
def expenses_export(request):
    feuser = request.feuser
    mode = _get_period_mode(request)

    if mode == "year":
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
        label = str(year)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)
        label = date(year, month, 1).strftime("%B_%Y")

    expenses = (
        Expense.objects.filter(
            owning_feuser=feuser,
            date_due__gte=start,
            date_due__lte=end,
            is_dummy=False,
        )
        .select_related("category")
        .prefetch_related("tags")
        .order_by("date_due", "date_created")
    )
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="expenses_{label}.csv"'
    w = csv.writer(response)
    w.writerow(["date_due", "title", "type", "value", "payee", "category", "tags", "note", "settled"])
    for e in expenses:
        w.writerow([
            e.date_due or "",
            e.title,
            e.type,
            e.value,
            e.payee,
            e.category.title if e.category else "",
            "|".join(t.title for t in e.tags.all()),
            e.note,
            e.settled,
        ])
    return response


@feuser_required
def expense_create(request):
    feuser = request.feuser
    if request.method == "POST":
        form = ExpenseForm(request.POST, feuser=feuser)
        buddy = _parse_buddy_post(request.POST, feuser)
        if form.is_valid() and (buddy is None or buddy["valid"]):
            expense = form.save(commit=False)
            if buddy and buddy["upfront_type"] == "feuser" and buddy["upfront_feuser"]:
                # Expense belongs to the other user; feuser initiated it
                other = buddy["upfront_feuser"]
                expense.owning_feuser = other
                expense.buddy_approved = False
                expense.project = buddy.get("group")
                expense.save()
                form.save_m2m()
                # At this point expense.category/tags belong to feuser (creating user).
                # Save an overlay for the creating feuser, then reconcile the expense
                # to the owning feuser's matching tags/categories.
                from budget.services import upsert_overlay, create_participant_overlays
                from buddies.services import BuddyEmailService, BuddyExpenseService
                creating_category = expense.category
                creating_tags = list(expense.tags.all())
                upsert_overlay(expense, feuser, creating_category, creating_tags)
                BuddyExpenseService.reconcile_categories_tags(expense, other)
                expense.save(update_fields=["category"])
                _apply_solo_spendings(expense, buddy, feuser)
                BuddyExpenseService.set_buddy_spendings(expense, buddy["spendings"])
                create_participant_overlays(expense)
                BuddyEmailService.send_expense_approval_request(expense, feuser)
                BuddyEmailService.notify_expense_created(expense, feuser)
                if expense.project:
                    expense.project.update_lastmod()
            else:
                expense.owning_feuser = feuser
                if buddy:
                    expense.is_dummy = (buddy["upfront_type"] == "dummy")
                    expense.upfront_payee_dummy = buddy.get("upfront_dummy")
                    expense.project = buddy.get("group")
                    # Dummy upfront payer in a project requires admin approval unless creator is admin
                    if (buddy["upfront_type"] == "dummy"
                            and expense.project
                            and expense.project.admin_feuser_id != feuser.pk):
                        expense.buddy_approved = False
                expense.save()
                form.save_m2m()
                if buddy:
                    from buddies.services import BuddyExpenseService, BuddyEmailService
                    from budget.services import create_participant_overlays
                    _apply_solo_spendings(expense, buddy, feuser)
                    BuddyExpenseService.set_buddy_spendings(expense, buddy["spendings"])
                    create_participant_overlays(expense)
                    BuddyEmailService.notify_expense_created(expense, feuser)
                    if expense.project:
                        expense.project.update_lastmod()
            set_initial_notification_class(expense)
            if buddy and buddy["upfront_type"] == "dummy" and buddy.get("upfront_dummy"):
                back = _safe_back_url(request.POST.get("back", ""))
                if not back:
                    from django.urls import reverse
                    dummy_name = buddy["upfront_dummy"].display_name + " (offline member)"
                    summary_url = reverse("buddies:buddy_summary")
                    messages.info(
                        request,
                        mark_safe(
                            f'"{expense.title}" was saved. Since <strong>{dummy_name}</strong> paid upfront, '
                            f'this expense won\'t appear in your regular expense list'
                            f' — you\'ll find it under <a href="{summary_url}">Buddy Expenses</a>.'
                        ),
                    )
                return HttpResponseRedirect(back) if back else redirect("buddies:buddy_summary")
            back = _safe_back_url(request.POST.get("back", ""))
            return HttpResponseRedirect(back) if back else redirect("budget:expenses_list")
    else:
        form = ExpenseForm(feuser=feuser, initial={"type": "expense", "settled": True, "notify": True})

    preselect_project_id = ""
    raw_pid = request.GET.get("project", "")
    if raw_pid:
        try:
            pid = int(raw_pid)
            from buddies.models import Project
            if Project.objects.filter(uid=pid, members__feuser=feuser, archived=False).exists():
                preselect_project_id = pid
        except (ValueError, TypeError):
            pass

    return render(request, "budget/expense_form.html", {
        "active_nav": "expenses",
        "form": form,
        "back_url": _safe_back_url(request.GET.get("back", "")),
        "existing_group_id": preselect_project_id,
        "is_buddy_expense": bool(preselect_project_id),
        "existing_mode": "group" if preselect_project_id else "single",
        **_buddy_context(feuser),
    })


@feuser_required
def expense_edit(request, uid):
    feuser = request.feuser
    expense = Expense.objects.filter(uid=uid, owning_feuser=feuser).first()
    is_admin_edit = False
    if expense is None:
        # Group admins may edit dummy-upfront expenses in their group.
        expense = get_object_or_404(
            Expense,
            uid=uid,
            is_dummy=True,
            project__admin_feuser=feuser,
        )
        is_admin_edit = True
    form_feuser = expense.owning_feuser if is_admin_edit else feuser
    if expense.type == TransactionType.CARRY_OVER:
        return redirect("budget:expenses_list")
    if expense.is_buddies_settlement and not expense.settlement_can_edit:
        return redirect("budget:expenses_list")
    # Non-admin group members cannot edit an approved group settlement: only the
    # group admin may do so. (The is_admin_edit path already bypasses this for
    # dummy-upfront expenses; here we catch dummy-creditor group settlements.)
    if (not is_admin_edit
            and expense.is_buddies_settlement
            and expense.buddy_approved
            and expense.project_id):
        from buddies.models import Project
        admin_pk = Project.objects.filter(uid=expense.project_id) \
            .values_list("admin_feuser_id", flat=True).first()
        if admin_pk != feuser.pk:
            return redirect("budget:expenses_list")
    if request.method == "POST":
        was_settled = expense.settled
        # Snapshot old buddy state before any changes are applied
        _old_title = expense.title
        _old_value = expense.value
        _old_participants = {
            bs.participant_feuser_id: (bs.participant_feuser, bs.share_percent)
            for bs in expense.buddy_spendings
            .select_related("participant_feuser")
            .filter(participant_feuser__isnull=False)
        }
        form = ExpenseForm(request.POST, instance=expense, feuser=form_feuser)
        buddy = _parse_buddy_post(request.POST, feuser)
        if form.is_valid() and (buddy is None or buddy["valid"]):
            _pre_edit_project = expense.project
            form.save()
            if buddy:
                new_type = buddy["upfront_type"]
                new_feuser = buddy.get("upfront_feuser")
                new_dummy = buddy.get("upfront_dummy")
                expense.project = buddy.get("group")
                expense.save(update_fields=["project"])
                # Detect payer change and apply service logic
                payer_changed = (
                    (new_type == "feuser" and new_feuser and new_feuser.pk != feuser.pk) or
                    (new_type == "dummy" and new_dummy and new_dummy != expense.upfront_payee_dummy) or
                    (new_type == "me" and expense.is_dummy)
                )
                from buddies.services import BuddyExpenseService, BuddyEmailService
                if payer_changed:
                    expense = BuddyExpenseService.change_upfront_payer(
                        expense,
                        new_payer_feuser=(new_feuser if new_type == "feuser" else None),
                        new_payer_dummy=(new_dummy if new_type == "dummy" else None),
                    )
                    # Non-admin changing payer to a project dummy needs admin approval
                    if new_type == "dummy" and new_dummy:
                        proj = buddy.get("group")
                        if proj and proj.admin_feuser_id != feuser.pk:
                            expense.buddy_approved = False
                            expense.save(update_fields=["buddy_approved"])
                    if new_type == "feuser" and new_feuser:
                        BuddyEmailService.send_expense_approval_request(expense, feuser)
                        BuddyEmailService.notify_expense_updated(
                            expense, feuser, _old_title, _old_value, _old_participants,
                            extra_notify_feuser=(expense.owning_feuser if is_admin_edit else None),
                        )
                        # Expense now belongs to other user; redirect without further editing
                        return redirect("budget:expenses_list")
                # Skip for settlements: creditor share must not change
                if not expense.is_buddies_settlement:
                    _apply_solo_spendings(expense, buddy, feuser)
                    BuddyExpenseService.set_buddy_spendings(expense, buddy["spendings"])
                BuddyEmailService.notify_expense_updated(
                    expense, feuser, _old_title, _old_value, _old_participants,
                    extra_notify_feuser=(expense.owning_feuser if is_admin_edit else None),
                )
                if expense.project:
                    expense.project.update_lastmod()
                if _pre_edit_project and _pre_edit_project != expense.project:
                    _pre_edit_project.update_lastmod()
            else:
                # Buddy payment removed: clear all buddy data
                expense.buddy_spendings.all().delete()
                expense.is_dummy = False
                expense.buddy_approved = True
                expense.upfront_payee_dummy = None
                expense.project = None
                expense.save(update_fields=["is_dummy", "buddy_approved", "upfront_payee_dummy", "project"])
                if _pre_edit_project:
                    _pre_edit_project.update_lastmod()
                if _old_participants:
                    from buddies.services import BuddyEmailService
                    BuddyEmailService.notify_expense_updated(
                        expense, feuser, _old_title, _old_value, _old_participants,
                        extra_notify_feuser=(expense.owning_feuser if is_admin_edit else None),
                    )

            if expense.is_buddies_settlement and not expense.buddy_approved:
                # Notify the creditor using the pre-edit participant snapshot.
                # We cannot rely on the post-edit spendings because the JS
                # auto-adds ME as a participant when the upfront payer is a
                # dummy, which would incorrectly pick the admin as the creditor.
                from buddies.services import BuddyEmailService
                _creditor = next(
                    (fu for (fu, _) in _old_participants.values()
                     if fu.pk != expense.owning_feuser_id),
                    None,
                )
                if _creditor:
                    BuddyEmailService.send_settlement_updated_notification(
                        expense, _creditor
                    )
            if not was_settled and expense.settled:
                send_settled_notification(expense)
            else:
                set_initial_notification_class(expense)
            back = _safe_back_url(request.POST.get("back", ""))
            return HttpResponseRedirect(back) if back else redirect("budget:expenses_list")
    else:
        form = ExpenseForm(instance=expense, feuser=form_feuser)

    # Determine current upfront payer for pre-population
    if expense.is_dummy and expense.upfront_payee_dummy_id:
        existing_upfront_type = "dummy"
        existing_upfront_id = expense.upfront_payee_dummy_id
    elif not expense.is_dummy and expense.buddy_spendings.exists():
        existing_upfront_type = "me"
        existing_upfront_id = form_feuser.pk
    else:
        existing_upfront_type = "me"
        existing_upfront_id = form_feuser.pk

    is_buddy_expense = expense.buddy_spendings.exists() or expense.is_dummy or bool(expense.project_id)

    return render(request, "budget/expense_form.html", {
        "active_nav": "expenses",
        "form": form,
        "expense": expense,
        "back_url": request.GET.get("back", ""),
        "is_buddy_expense": is_buddy_expense,
        "existing_upfront_type": existing_upfront_type,
        "existing_upfront_id": existing_upfront_id,
        "existing_spendings_json": _existing_buddy_json(expense),
        "existing_mode": "group" if expense.project_id else "single",
        "existing_group_id": expense.project_id or "",
        **_buddy_context(feuser),
    })


@feuser_required
@require_POST
def expense_delete(request, uid):
    expense = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if expense.type == TransactionType.CARRY_OVER:
        return redirect("budget:expenses_list")
    if expense.is_buddies_settlement:
        if not expense.settlement_can_delete:
            return redirect("budget:expenses_list")
        # Non-admin group members cannot delete an approved group settlement via
        # this endpoint; the group-specific delete view handles permissions there.
        if expense.buddy_approved and expense.project_id:
            from buddies.models import Project
            admin_pk = Project.objects.filter(uid=expense.project_id) \
                .values_list("admin_feuser_id", flat=True).first()
            if admin_pk != request.feuser.pk:
                return redirect("budget:expenses_list")
        # Notify real-user creditor when an unapproved settlement is cancelled
        if not expense.buddy_approved:
            from buddies.services import BuddyEmailService
            bs = expense.buddy_spendings.select_related("participant_feuser").filter(
                participant_feuser__isnull=False
            ).first()
            if bs:
                BuddyEmailService.send_settlement_cancelled_notification(
                    expense, bs.participant_feuser
                )
    _proj = expense.project
    expense.delete()
    if _proj:
        _proj.update_lastmod()
    messages.success(request, "Expense deleted.")
    back = _safe_back_url(request.POST.get("back", ""))
    return HttpResponseRedirect(back) if back else redirect("budget:expenses_list")


@feuser_required
@require_POST
def expense_bulk_action(request):
    feuser = request.feuser
    action = request.POST.get("action")
    uids_raw = request.POST.getlist("uid")
    try:
        uids = [int(u) for u in uids_raw if u]
    except (ValueError, TypeError):
        uids = []

    if uids and action in ("settle", "unsettle", "delete"):
        qs = Expense.objects.filter(owning_feuser=feuser, uid__in=uids, is_dummy=False)
        if action == "settle":
            if len(uids) == 1:
                single = qs.filter(settled=False).select_related("owning_feuser").first()
                qs.update(settled=True)
                if single:
                    single.settled = True
                    send_settled_notification(single)
            else:
                qs.update(settled=True)
        elif action == "unsettle":
            qs.update(settled=False)
        elif action == "delete":
            qs_del = qs.exclude(is_buddies_settlement=True)
            from buddies.models import Project as _Project
            affected_project_pks = set(
                qs_del.filter(project__isnull=False).values_list("project_id", flat=True)
            )
            qs_del.delete()
            for _pk in affected_project_pks:
                try:
                    _Project.objects.get(pk=_pk).update_lastmod()
                except _Project.DoesNotExist:
                    pass

    referer = request.META.get("HTTP_REFERER")
    if referer:
        return HttpResponseRedirect(referer)
    return redirect("budget:expenses_list")


@feuser_required
def expense_settle_via_email(request, uid):
    """Settle an expense via a link in a notification email (GET, session-protected)."""
    expense = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if not expense.settled:
        expense.settled = True
        expense.save(update_fields=["settled"])
        send_settled_notification(expense)
    return redirect("budget:expenses_list")


@feuser_required
def expense_mute_notifications(request, uid):
    """Disable notifications for a single expense via a link in a notification email."""
    expense = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    expense.notify = False
    expense.save(update_fields=["notify"])
    return redirect("budget:expenses_list")


@feuser_required
def mute_all_notifications(request):
    """Disable all email notifications for the current user."""
    from django.utils import timezone as _tz
    request.feuser.email_notifications = False
    request.feuser.last_mod = _tz.now()
    request.feuser.save(update_fields=["email_notifications", "last_mod"])
    return redirect("budget:expenses_list")


@feuser_required
@require_POST
def expense_clone(request, uid):
    original = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if original.type == TransactionType.CARRY_OVER:
        return redirect("budget:expenses_list")
    if original.is_buddies_settlement:
        return redirect("budget:expenses_list")
    tags = list(original.tags.all())
    original.pk = None
    original.title = f"CLONE - {original.title}"
    original.save()
    original.tags.set(tags)
    return redirect("budget:expense_edit", uid=original.pk)


@feuser_required
def expense_edit_overlay(request, uid):
    """Lite editor: participants set their own category/tags for a buddy expense."""
    feuser = request.feuser
    from buddies.models import BuddySpending
    spending = get_object_or_404(BuddySpending, expense__uid=uid, participant_feuser=feuser)
    expense = spending.expense

    overlay = ExpenseDataOverlay.objects.filter(expense=expense, feuser=feuser).first()

    if request.method == "POST":
        form = ExpenseOverlayForm(request.POST, feuser=feuser)
        if form.is_valid():
            category = form.cleaned_data["category"]
            tags = list(form.cleaned_data["tags"])
            note = form.cleaned_data["note"]
            from ..services import upsert_overlay
            upsert_overlay(expense, feuser, category, tags, note=note)
            back = _safe_back_url(request.POST.get("back", ""))
            return HttpResponseRedirect(back) if back else redirect("buddies:buddy_summary")
    else:
        initial = {}
        if overlay:
            initial["category"] = overlay.category
            initial["tags"] = list(overlay.tags.all())
            initial["note"] = overlay.note
        form = ExpenseOverlayForm(feuser=feuser, initial=initial)

    currency = expense.owning_feuser.currency
    if expense.is_dummy and expense.upfront_payee_dummy:
        upfront_payer = f"{expense.upfront_payee_dummy.display_name} (offline buddy)"
    else:
        owner = expense.owning_feuser
        upfront_payer = f"{owner.first_name} {owner.last_name}".strip() or owner.email

    participant_shares = []
    for bs in expense.buddy_spendings.select_related("participant_feuser", "participant_dummy").all():
        if bs.participant_feuser:
            u = bs.participant_feuser
            name = f"{u.first_name} {u.last_name}".strip() or u.email
        else:
            name = f"{bs.participant_dummy.display_name} (offline member)"
        amount = (expense.value * bs.share_percent / 100).quantize(expense.value)
        participant_shares.append({
            "name": name,
            "percent": bs.share_percent,
            "amount": amount,
            "is_me": bs.participant_feuser == feuser,
        })

    return render(request, "budget/expense_edit_overlay.html", {
        "form": form,
        "expense": expense,
        "back_url": request.GET.get("back", ""),
        "currency": currency,
        "upfront_payer": upfront_payer,
        "participant_shares": participant_shares,
    })
