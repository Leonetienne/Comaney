from django.contrib import admin
from django.utils.html import format_html

from .models import FeUser


@admin.register(FeUser)
class FeUserAdmin(admin.ModelAdmin):
    list_display = ("email", "first_name", "last_name", "is_active", "is_confirmed", "created_at")
    search_fields = ("email", "first_name", "last_name")
    list_filter = ("is_active", "is_confirmed")
    # password stores the raw hash — editing it here would break login.
    # created_at is auto-set and must not be changed.
    readonly_fields = ("created_at", "password", "password_note")

    def password_note(self, obj):
        return format_html(
            '<span style="color: #c0392b; font-weight: bold;">'
            "The password field above contains the raw hash. "
            "Do not edit it here — it will not be re-hashed and will break login. "
            "To change a user's password, use the password-reset flow in the user frontend."
            "</span>"
        )
    password_note.short_description = ""

    def has_add_permission(self, request):
        # New users must register via the user frontend — the admin cannot
        # create accounts with properly hashed passwords or confirmed state.
        return False
