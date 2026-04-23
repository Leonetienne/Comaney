from django.contrib import admin

from .models import FeUser


@admin.register(FeUser)
class FeUserAdmin(admin.ModelAdmin):
    list_display = ("email", "first_name", "last_name", "is_active", "is_confirmed", "created_at")
    search_fields = ("email", "first_name", "last_name")
    list_filter = ("is_active", "is_confirmed")
