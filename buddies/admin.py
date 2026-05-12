from django.contrib import admin

from .models import (
    BuddyGroup,
    BuddyGroupInvite,
    BuddyGroupMember,
    BuddyInvite,
    BuddyLink,
    BuddyOnboardingInvite,
    BuddySpending,
    DummyMergeInvite,
    DummyUser,
)


@admin.register(BuddyGroup)
class BuddyGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "admin_feuser", "created_at"]
    search_fields = ["name", "admin_feuser__email"]


@admin.register(BuddyGroupMember)
class BuddyGroupMemberAdmin(admin.ModelAdmin):
    list_display = ["group", "feuser", "dummy", "joined_at"]
    list_filter = ["group"]


@admin.register(BuddyGroupInvite)
class BuddyGroupInviteAdmin(admin.ModelAdmin):
    list_display = ["group", "inviting_feuser", "invitee_email", "created_at", "expires_at"]


@admin.register(DummyUser)
class DummyUserAdmin(admin.ModelAdmin):
    list_display = ["display_name", "owning_feuser", "owning_group", "created_at"]
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


@admin.register(BuddyOnboardingInvite)
class BuddyOnboardingInviteAdmin(admin.ModelAdmin):
    list_display = ["inviting_feuser", "invitee_email", "dummy", "group", "created_at", "expires_at"]
    search_fields = ["invitee_email", "inviting_feuser__email"]


@admin.register(BuddySpending)
class BuddySpendingAdmin(admin.ModelAdmin):
    list_display = ["expense", "participant_feuser", "participant_dummy", "share_percent"]
