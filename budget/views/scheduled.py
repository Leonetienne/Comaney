from datetime import date

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..decorators import feuser_required
from ..forms import ScheduledExpenseForm
from ..models import ScheduledExpense


@feuser_required
def scheduled_list(request):
    scheduled = (
        ScheduledExpense.objects.filter(owning_feuser=request.feuser)
        .select_related("category")
        .prefetch_related("tags")
    )
    return render(request, "budget/scheduled_list.html", {
        "active_nav": "scheduled",
        "scheduled": scheduled,
        "today": date.today(),
    })


@feuser_required
def scheduled_create(request):
    if request.method == "POST":
        form = ScheduledExpenseForm(request.POST, feuser=request.feuser)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.owning_feuser = request.feuser
            obj.save()
            form.save_m2m()
            return redirect("budget:scheduled_list")
    else:
        form = ScheduledExpenseForm(
            feuser=request.feuser,
            initial={"type": "expense", "default_auto_settle_on_due_date": True, "notify": True},
        )
    return render(request, "budget/scheduled_form.html", {
        "active_nav": "scheduled",
        "form": form,
    })


@feuser_required
def scheduled_edit(request, uid):
    obj = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=request.feuser)
    if request.method == "POST":
        form = ScheduledExpenseForm(request.POST, instance=obj, feuser=request.feuser)
        if form.is_valid():
            form.save()
            return redirect("budget:scheduled_list")
    else:
        form = ScheduledExpenseForm(instance=obj, feuser=request.feuser)
    return render(request, "budget/scheduled_form.html", {
        "active_nav": "scheduled",
        "form": form,
        "scheduled": obj,
    })


@feuser_required
@require_POST
def scheduled_delete(request, uid):
    obj = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=request.feuser)
    obj.delete()
    return redirect("budget:scheduled_list")


@feuser_required
@require_POST
def scheduled_clone(request, uid):
    original = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=request.feuser)
    tags = list(original.tags.all())
    original.pk = None
    original.title = f"CLONE - {original.title}"
    original.save()
    original.tags.set(tags)
    return redirect("budget:scheduled_edit", uid=original.pk)
