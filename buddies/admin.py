from django.contrib import admin

from .models import BuddyInvite, BuddyLink, BuddySpending, DummyMergeInvite, DummyUser


@admin.register(DummyUser)
class DummyUserAdmin(admin.ModelAdmin):
    list_display = ["display_name", "owning_feuser", "created_at"]
    search_fields = ["display_name", "owning_feuser__email"]


@admin.register(BuddyLink)
class BuddyLinkAdmin(admin.ModelAdmin):
    list_display = ["user_a", "user_b", "created_at"]


@admin.register(BuddyInvite)
class BuddyInviteAdmin(admin.ModelAdmin):
    list_display = ["inviter", "invitee_email", "created_at", "expires_at"]


@admin.register(DummyMergeInvite)
class DummyMergeInviteAdmin(admin.ModelAdmin):
    list_display = ["inviting_feuser", "dummy", "invited_feuser", "created_at"]


@admin.register(BuddySpending)
class BuddySpendingAdmin(admin.ModelAdmin):
    list_display = ["expense", "participant_feuser", "participant_dummy", "share_percent"]
