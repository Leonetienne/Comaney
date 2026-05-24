import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone

INVITE_EXPIRY_DAYS = 7


class ProjectInvite(models.Model):
    """Invitation to join a project. Also establishes a BuddyLink if not already buddies."""
    uid = models.BigAutoField(primary_key=True)
    group = models.ForeignKey("buddies.Project", on_delete=models.CASCADE, related_name="invites")
    inviting_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="group_invites_sent"
    )
    invitee_email = models.EmailField(db_index=True)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_mod = models.DateTimeField(default=timezone.now)

    def is_valid(self):
        return timezone.now() < self.expires_at

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Project invite to {self.group} for {self.invitee_email}"


BuddyGroupInvite = ProjectInvite


class BuddyInvite(models.Model):
    uid = models.BigAutoField(primary_key=True)
    inviter = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="buddy_invites_sent"
    )
    invitee_email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_mod = models.DateTimeField(default=timezone.now)

    def is_valid(self):
        return timezone.now() < self.expires_at

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Invite from {self.inviter} to {self.invitee_email}"


class DummyMergeInvite(models.Model):
    uid = models.BigAutoField(primary_key=True)
    inviting_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="merge_invites_sent"
    )
    dummy = models.ForeignKey(
        "buddies.DummyUser", on_delete=models.CASCADE, related_name="merge_invites"
    )
    invited_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="merge_invites_received"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_mod = models.DateTimeField(default=timezone.now)

    def is_valid(self):
        return timezone.now() < self.expires_at

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Merge {self.dummy} into {self.invited_feuser}"


class BuddyOnboardingInvite(models.Model):
    """Sent when inviting a non-existing user.

    dummy set: merge invite for a dummy user.
    group set: project join invite (also creates BuddyLink on accept).
    dummy + group set: merge invite for a project dummy.
    Neither set: plain buddy invite.
    """

    uid = models.BigAutoField(primary_key=True)
    inviting_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="onboarding_invites_sent"
    )
    dummy = models.ForeignKey(
        "buddies.DummyUser", on_delete=models.CASCADE, null=True, blank=True, related_name="onboarding_invites"
    )
    group = models.ForeignKey(
        "buddies.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="onboarding_invites"
    )
    invitee_email = models.EmailField(db_index=True)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_mod = models.DateTimeField(default=timezone.now)

    def is_valid(self):
        return timezone.now() < self.expires_at

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS)
        super().save(*args, **kwargs)

    def __str__(self):
        if self.dummy_id and self.group_id:
            kind = "group-merge"
        elif self.dummy_id:
            kind = "merge"
        elif self.group_id:
            kind = "group"
        else:
            kind = "buddy"
        return f"Onboarding {kind} invite from {self.inviting_feuser} to {self.invitee_email}"
