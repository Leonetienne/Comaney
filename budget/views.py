import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decorators import feuser_required
from .forms import ExpenseForm, ScheduledExpenseForm
from .models import Category, Expense, ScheduledExpense, Tag


@feuser_required
def dashboard(request):
    feuser = request.feuser
    total_expenses = Expense.objects.filter(owning_feuser=feuser).count()
    return render(request, "budget/dashboard.html", {
        "active_nav": "dashboard",
        "total_expenses": total_expenses,
    })


@feuser_required
def categories_tags(request):
    feuser = request.feuser
    categories = Category.objects.filter(owning_feuser=feuser)
    tags = Tag.objects.filter(owning_feuser=feuser)
    return render(request, "budget/categories_tags.html", {
        "active_nav": "categories_tags",
        "categories": categories,
        "tags": tags,
    })


@feuser_required
@require_POST
def category_create(request):
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    category = Category.objects.create(owning_feuser=request.feuser, title=title)
    return JsonResponse({"uid": category.uid, "title": category.title})


@feuser_required
@require_POST
def category_delete(request, uid):
    category = get_object_or_404(Category, uid=uid, owning_feuser=request.feuser)
    category.delete()
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def tag_create(request):
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    tag = Tag.objects.create(owning_feuser=request.feuser, title=title)
    return JsonResponse({"uid": tag.uid, "title": tag.title})


@feuser_required
@require_POST
def tag_delete(request, uid):
    tag = get_object_or_404(Tag, uid=uid, owning_feuser=request.feuser)
    tag.delete()
    return JsonResponse({"ok": True})


@feuser_required
def expenses_list(request):
    expenses = (
        Expense.objects.filter(owning_feuser=request.feuser)
        .select_related("category")
        .prefetch_related("tags")
    )
    return render(request, "budget/expenses_list.html", {
        "active_nav": "expenses",
        "expenses": expenses,
    })


@feuser_required
def expense_create(request):
    if request.method == "POST":
        form = ExpenseForm(request.POST, feuser=request.feuser)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.owning_feuser = request.feuser
            expense.save()
            form.save_m2m()
            return redirect("budget:expenses_list")
    else:
        form = ExpenseForm(feuser=request.feuser, initial={"type": "expense", "settled": True})
    return render(request, "budget/expense_form.html", {
        "active_nav": "expenses",
        "form": form,
    })


@feuser_required
def expense_edit(request, uid):
    expense = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if request.method == "POST":
        form = ExpenseForm(request.POST, instance=expense, feuser=request.feuser)
        if form.is_valid():
            form.save()
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
    expense.delete()
    return redirect("budget:expenses_list")


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
        form = ScheduledExpenseForm(feuser=request.feuser, initial={"type": "expense"})
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
