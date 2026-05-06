import csv
from datetime import date

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..date_utils import financial_month_range, financial_year_range
from ..decorators import feuser_required
from ..forms import ExpenseForm
from ..models import Expense, TransactionType
from ..notifications import send_settled_notification, set_initial_notification_class
from ._period import _get_month, _get_period_mode, _get_year, _month_nav_context, _year_nav_context


@feuser_required
def expenses_list(request):
    feuser = request.feuser
    mode = _get_period_mode(request)

    if mode == "year":
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _year_nav_context(year, feuser.month_start_day, feuser.month_start_prev)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _month_nav_context(year, month, feuser.month_start_day, feuser.month_start_prev)

    expenses = (
        Expense.objects.filter(
            owning_feuser=feuser,
            date_due__gte=start,
            date_due__lte=end,
        )
        .select_related("category")
        .prefetch_related("tags")
        .order_by("-date_due", "-date_created")
    )
    ctx = {"active_nav": "expenses", "expenses": expenses}
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
    if request.method == "POST":
        form = ExpenseForm(request.POST, feuser=request.feuser)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.owning_feuser = request.feuser
            expense.save()
            form.save_m2m()
            set_initial_notification_class(expense)
            return redirect("budget:expenses_list")
    else:
        form = ExpenseForm(feuser=request.feuser, initial={"type": "expense", "settled": True, "notify": True})
    return render(request, "budget/expense_form.html", {
        "active_nav": "expenses",
        "form": form,
    })


@feuser_required
def expense_edit(request, uid):
    expense = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if expense.type == TransactionType.CARRY_OVER:
        return redirect("budget:expenses_list")
    if request.method == "POST":
        was_settled = expense.settled
        form = ExpenseForm(request.POST, instance=expense, feuser=request.feuser)
        if form.is_valid():
            form.save()
            if not was_settled and expense.settled:
                send_settled_notification(expense)
            else:
                set_initial_notification_class(expense)
            return redirect("budget:expenses_list")
    else:
        form = ExpenseForm(instance=expense, feuser=request.feuser)
    return render(request, "budget/expense_form.html", {
        "active_nav": "expenses",
        "form": form,
        "expense": expense,
    })


@feuser_required
@require_POST
def expense_delete(request, uid):
    expense = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if expense.type == TransactionType.CARRY_OVER:
        return redirect("budget:expenses_list")
    expense.delete()
    return redirect("budget:expenses_list")


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
        qs = Expense.objects.filter(owning_feuser=feuser, uid__in=uids)
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
            qs.delete()

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
    request.feuser.email_notifications = False
    request.feuser.save(update_fields=["email_notifications"])
    return redirect("budget:expenses_list")


@feuser_required
@require_POST
def expense_clone(request, uid):
    original = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if original.type == TransactionType.CARRY_OVER:
        return redirect("budget:expenses_list")
    tags = list(original.tags.all())
    original.pk = None
    original.title = f"CLONE - {original.title}"
    original.save()
    original.tags.set(tags)
    return redirect("budget:expense_edit", uid=original.pk)
