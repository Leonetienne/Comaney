from django.contrib import admin

from .models import Category, Expense, ScheduledExpense, Tag


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("title", "owning_feuser", "created_at")
    list_filter = ("owning_feuser",)
    search_fields = ("title",)
    readonly_fields = ("created_at",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("title", "owning_feuser", "created_at")
    list_filter = ("owning_feuser",)
    search_fields = ("title",)
    readonly_fields = ("created_at",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "value", "category", "settled", "date_due", "date_created", "owning_feuser")
    list_filter = ("type", "settled", "owning_feuser")
    search_fields = ("title", "note")
    filter_horizontal = ("tags",)
    readonly_fields = ("date_created",)


@admin.register(ScheduledExpense)
class ScheduledExpenseAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "value", "repeat_every_factor", "repeat_every_unit", "created_at", "owning_feuser")
    list_filter = ("type", "repeat_every_unit", "owning_feuser")
    search_fields = ("title", "note")
    filter_horizontal = ("tags",)
    readonly_fields = ("created_at",)
