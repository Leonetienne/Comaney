from django.contrib import admin

from .models import Category, Expense, ScheduledExpense, Tag


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("title", "owning_feuser")
    list_filter = ("owning_feuser",)
    search_fields = ("title",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("title", "owning_feuser")
    list_filter = ("owning_feuser",)
    search_fields = ("title",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "value", "category", "settled", "date_due", "owning_feuser")
    list_filter = ("type", "settled", "owning_feuser")
    search_fields = ("title", "note")
    filter_horizontal = ("tags",)


@admin.register(ScheduledExpense)
class ScheduledExpenseAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "value", "repeat_every_factor", "repeat_every_unit", "owning_feuser")
    list_filter = ("type", "repeat_every_unit", "owning_feuser")
    search_fields = ("title", "note")
    filter_horizontal = ("tags",)
