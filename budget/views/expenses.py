import csv
import secrets
import urllib.parse
from datetime import date

from comaney.csv_export import _csv_safe
from comaney.json_utils import safe_json

from django.contrib import messages
from django.utils.html import escape as html_escape
from django.utils.safestring import mark_safe
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from feusers.templatetags.feuser_tags import avatar_color as _avatar_color

from ..date_utils import financial_month_range, financial_year_range
from ..decorators import feuser_required
from ..forms import ExpenseForm, ExpenseOverlayForm
from ..models import Category, Expense, ExpenseDataOverlay, Tag
from ..expense_service import (
    BUDDY_TYPE_CONFLICT_MSG, ExpenseActionError, bulk_action, clone_expense, delete_expense,
    editable_expense, parse_assignment_post, participant_expense, save_new_expense, set_overlay,
    settle_expense, update_expense,
)
from ._period import _get_month, _get_period_mode, _get_year, _date_range_presets_context
from ._sharing import has_contact_or_multiuser_project


# ---------------------------------------------------------------------------
# Buddy payment helpers
# ---------------------------------------------------------------------------

def _buddy_context(feuser) -> dict:
    """
    Build the buddy/project widget config for the expense form.

    projects_data / contacts are also returned raw (not just JSON-encoded)
    so express_service._build_catalog()/​_validate_items() can enumerate the exact
    same list this request is about to render into the widget's JS config.
    Querying it twice would risk two different row orderings breaking the
    idx-based correspondence between the AI's catalog and the widget's arrays.
    """
    from buddies.services import BuddyQueryService, BuddyTrustService
    actual = list(BuddyQueryService.get_real_contacts(feuser))
    trusters = BuddyTrustService.trusters_of(feuser)
    dummy = list(BuddyQueryService.get_offline_contacts(feuser))
    contacts = [
        *[{"type": "feuser", "id": b.pk, "name": f"{b.first_name} {b.last_name}".strip() or b.email, "email": b.email,
           "autoAccepts": b.pk in trusters,
           "ppicUrl": b.ppic_url if b.profile_picture else "", "initials": b.initials, "avatarColor": _avatar_color(b.initials)} for b in actual],
        *[{"type": "dummy", "id": d.uid, "name": d.display_name + " (offline member)",
           "ppicUrl": d.ppic_url if d.profile_picture else "", "initials": d.initials, "avatarColor": _avatar_color(d.initials)} for d in dummy],
    ]
    # Only active (non-archived) projects appear in the expense form dropdown
    projects = BuddyQueryService.get_active_projects_for_feuser(feuser)
    projects_data = BuddyQueryService.projects_data_for_expense_form(feuser)
    return {
        "real_contacts": actual,
        "offline_contacts": dummy,
        "buddy_groups": projects,
        "projects_data": projects_data,
        "contacts_data": contacts,
        "projects_data_json": safe_json(projects_data),
        "contacts_json": safe_json(contacts),
    }


def _buddy_render_context_from_post(buddy, feuser) -> dict:
    """Rebuild the expense-assignment template context from a just-submitted
    (and rejected) buddy POST, so a failed submission doesn't appear to silently
    reset the user's project/buddy selection."""
    if not buddy:
        return {
            "is_buddy_expense": False,
            "existing_mode": "single",
            "existing_upfront_type": "me",
            "existing_upfront_id": feuser.pk,
            "existing_spendings_json": "[]",
            "existing_group_id": "",
            # A re-rendered submission carries the user's explicit participant
            # choice (even if empty); never auto-check all members over it.
            "respect_existing_participants": True,
        }
    if buddy["upfront_type"] == "feuser" and buddy.get("upfront_feuser"):
        upfront_id = buddy["upfront_feuser"].pk
    elif buddy["upfront_type"] == "dummy" and buddy.get("upfront_dummy"):
        upfront_id = buddy["upfront_dummy"].pk
    else:
        upfront_id = feuser.pk
    return {
        "is_buddy_expense": True,
        "existing_mode": buddy["mode"],
        "existing_upfront_type": buddy["upfront_type"],
        "existing_upfront_id": upfront_id,
        "existing_spendings_json": safe_json(buddy.get("spendings") or []),
        "existing_group_id": buddy["group"].pk if buddy.get("group") else "",
        "respect_existing_participants": True,
    }


def _existing_buddy_json(expense) -> str:
    """Serialise existing BuddySpending rows for a JS-editable expense form."""
    rows = []
    for bs in expense.buddy_spendings.select_related("participant_feuser", "participant_dummy").all():
        if bs.participant_feuser_id:
            rows.append({"type": "feuser", "id": bs.participant_feuser_id, "share_percent": float(bs.share_percent)})
        else:
            rows.append({"type": "dummy", "id": bs.participant_dummy_id, "share_percent": float(bs.share_percent)})
    return safe_json(rows)


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
    categories = list(
        Category.objects.filter(owning_feuser=feuser).order_by("title").values("uid", "title")
    )
    tags = list(
        Tag.objects.filter(owning_feuser=feuser).order_by("title").values("uid", "title")
    )
    ctx = {
        "active_nav": "expenses",
        "nav_show_sharing_toggle": has_contact_or_multiuser_project(feuser),
        "categories_json": safe_json(categories),
        "tags_json": safe_json(tags),
        "initial_date_from": request.GET.get("date_from", ""),
        "initial_date_to": request.GET.get("date_to", ""),
    }
    ctx.update(_date_range_presets_context(feuser))
    return render(request, "budget/expenses_list.html", ctx)


@feuser_required
def expenses_export(request):
    feuser = request.feuser
    date_from_raw = request.GET.get("date_from")
    date_to_raw   = request.GET.get("date_to")

    if date_from_raw and date_to_raw:
        try:
            start = date.fromisoformat(date_from_raw)
            end   = date.fromisoformat(date_to_raw)
            label = f"{start.isoformat()}_to_{end.isoformat()}"
        except ValueError:
            date_from_raw = None

    if not date_from_raw or not date_to_raw:
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
            _csv_safe(e.title),
            e.type,
            e.value,
            _csv_safe(e.payee),
            _csv_safe(e.category.title if e.category else ""),
            _csv_safe("|".join(t.title for t in e.tags.all())),
            _csv_safe(e.note),
            e.settled,
        ])
    return response


@feuser_required
def add_expense(request):
    from feusers.context_processors import current_feuser as build_feuser_context
    if not build_feuser_context(request)["ai_smart_create_available"]:
        return redirect("budget:expense_create")
    return render(request, "budget/add_expense.html", {"active_nav": "add_expense"})


@feuser_required
def expense_create(request):
    feuser = request.feuser
    if request.method == "POST":
        submitted_nonce = request.POST.get("form_nonce", "")
        session_nonce = request.session.pop("expense_create_nonce", None)
        if not session_nonce or submitted_nonce != session_nonce:
            # Duplicate submission (back + resubmit); redirect without creating
            back = _safe_back_url(request.POST.get("back", ""))
            return HttpResponseRedirect(back) if back else redirect("budget:expenses_list")

        form = ExpenseForm(request.POST, feuser=feuser)
        buddy = parse_assignment_post(request.POST, feuser)
        if form.is_valid() and (buddy is None or buddy["valid"]):
            expense = save_new_expense(feuser, form.save(commit=False), form.cleaned_data["tags"], buddy)
            if buddy and buddy["upfront_type"] == "dummy" and buddy.get("upfront_dummy"):
                back = _safe_back_url(request.POST.get("back", ""))
                if not back:
                    from django.urls import reverse
                    dummy_name = buddy["upfront_dummy"].display_name + " (offline member)"
                    summary_url = reverse("buddies:contact_summary")
                    messages.info(
                        request,
                        mark_safe(
                            f'"{html_escape(expense.title)}" was saved. Since <strong>{html_escape(dummy_name)}</strong> paid upfront, '
                            f'this expense won\'t appear in your regular expense list'
                            f' — you\'ll find it under <a href="{summary_url}">Contact Expenses</a>.'
                        ),
                    )
                return HttpResponseRedirect(back) if back else redirect("buddies:contact_summary")
            back = _safe_back_url(request.POST.get("back", ""))
            return HttpResponseRedirect(back) if back else redirect("budget:expenses_list")
        elif buddy and buddy.get("type_conflict"):
            messages.error(request, BUDDY_TYPE_CONFLICT_MSG)
    else:
        form = ExpenseForm(feuser=feuser, initial={"type": "expense", "settled": True, "notify": True})

    form_nonce = secrets.token_hex(32)
    request.session["expense_create_nonce"] = form_nonce

    if request.method == "POST":
        buddy_render_ctx = _buddy_render_context_from_post(buddy, feuser)
    else:
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
        buddy_render_ctx = {
            "existing_group_id": preselect_project_id,
            "is_buddy_expense": bool(preselect_project_id),
            "existing_mode": "group" if preselect_project_id else "single",
        }

    return render(request, "budget/expense_form.html", {
        "active_nav": "expenses",
        "form": form,
        "form_nonce": form_nonce,
        "back_url": _safe_back_url(request.GET.get("back", "")),
        **buddy_render_ctx,
        **_buddy_context(feuser),
    })


@feuser_required
def expense_edit(request, uid):
    feuser = request.feuser
    try:
        expense, is_admin_edit = editable_expense(feuser, uid)
    except Expense.DoesNotExist:
        raise Http404
    except ExpenseActionError:
        return redirect("budget:expenses_list")
    form_feuser = expense.owning_feuser if is_admin_edit else feuser
    if request.method == "POST":
        form = ExpenseForm(request.POST, instance=expense, feuser=form_feuser)
        buddy = parse_assignment_post(request.POST, feuser)
        if form.is_valid() and (buddy is None or buddy["valid"]):
            update_expense(feuser, expense, form.save, buddy, is_admin_edit=is_admin_edit)
            back = _safe_back_url(request.POST.get("back", ""))
            return HttpResponseRedirect(back) if back else redirect("budget:expenses_list")
        elif buddy and buddy.get("type_conflict"):
            messages.error(request, BUDDY_TYPE_CONFLICT_MSG)
    else:
        form = ExpenseForm(instance=expense, feuser=form_feuser)

    if request.method == "POST":
        buddy_render_ctx = _buddy_render_context_from_post(buddy, feuser)
    else:
        # Determine current upfront payer for pre-population
        if expense.is_dummy and expense.upfront_payee_dummy_id:
            existing_upfront_type = "dummy"
            existing_upfront_id = expense.upfront_payee_dummy_id
        else:
            existing_upfront_type = "me"
            existing_upfront_id = form_feuser.pk
        buddy_render_ctx = {
            "is_buddy_expense": expense.buddy_spendings.exists() or expense.is_dummy or bool(expense.project_id),
            "existing_upfront_type": existing_upfront_type,
            "existing_upfront_id": existing_upfront_id,
            "existing_spendings_json": _existing_buddy_json(expense),
            "existing_mode": "group" if expense.project_id else "single",
            "existing_group_id": expense.project_id or "",
            # Editing a saved expense: keep its participant selection as-is (a
            # zero-participant project expense must not re-check every member).
            "respect_existing_participants": True,
        }

    return render(request, "budget/expense_form.html", {
        "active_nav": "expenses",
        "form": form,
        "expense": expense,
        "back_url": request.GET.get("back", ""),
        **buddy_render_ctx,
        **_buddy_context(feuser),
    })


@feuser_required
@require_POST
def expense_delete(request, uid):
    expense = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    try:
        delete_expense(request.feuser, expense)
    except ExpenseActionError:
        return redirect("budget:expenses_list")
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

    result = None
    if uids:
        try:
            result = bulk_action(
                feuser, action, uids,
                tag_uid=request.POST.get("tag_uid", ""),
                category_uid=request.POST.get("category_uid", ""),
            )
        except ExpenseActionError:
            pass

    if result and result.foreign:
        n = result.foreign
        s = "s" if n != 1 else ""
        if action in ("settle", "unsettle", "delete"):
            messages.warning(
                request,
                f"{n} expense{s} could not be updated — they do not belong to you.",
            )
        elif result.via_overlay:
            s = "s" if result.via_overlay != 1 else ""
            messages.info(
                request,
                f"{result.via_overlay} expense{s} were updated in your personal view only — they do not belong to you.",
            )

    referer = request.META.get("HTTP_REFERER")
    if referer:
        return HttpResponseRedirect(referer)
    return redirect("budget:expenses_list")


@feuser_required
def expense_settle_via_email(request, uid):
    """Settle an expense via a link in a notification email (GET, session-protected)."""
    settle_expense(get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser))
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
    try:
        original = clone_expense(request.feuser, original)
    except ExpenseActionError:
        return redirect("budget:expenses_list")
    return redirect("budget:expense_edit", uid=original.pk)


@feuser_required
def expense_edit_overlay(request, uid):
    """Lite editor: participants set their own category/tags for a buddy expense."""
    feuser = request.feuser
    try:
        expense = participant_expense(feuser, uid)
    except Expense.DoesNotExist:
        raise Http404

    overlay = ExpenseDataOverlay.objects.filter(expense=expense, feuser=feuser).first()

    if request.method == "POST":
        form = ExpenseOverlayForm(request.POST, feuser=feuser)
        if form.is_valid():
            set_overlay(
                feuser, expense, form.cleaned_data["category"], form.cleaned_data["tags"],
                note=form.cleaned_data["note"],
            )
            back = _safe_back_url(request.POST.get("back", ""))
            return HttpResponseRedirect(back) if back else redirect("buddies:contact_summary")
    else:
        initial = {}
        if overlay:
            initial["category"] = overlay.category
            initial["tags"] = list(overlay.tags.all())
            initial["note"] = overlay.note
        form = ExpenseOverlayForm(feuser=feuser, initial=initial)

    currency = expense.owning_feuser.currency
    if expense.is_dummy and expense.upfront_payee_dummy:
        upfront_payer = f"{expense.upfront_payee_dummy.display_name} (offline contact)"
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
