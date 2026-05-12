import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone

INVITE_EXPIRY_DAYS = 7


class BuddyGroup(models.Model):
    uid = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=128)
    admin_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="administered_groups"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class DummyUser(models.Model):
    uid = models.BigAutoField(primary_key=True)
    owning_feuser = models.ForeignKey(
        "feusers.FeUser", null=True, blank=True, on_delete=models.CASCADE, related_name="dummy_buddies"
    )
    owning_group = models.ForeignKey(
        BuddyGroup, null=True, blank=True, on_delete=models.CASCADE, related_name="dummy_members"
    )
    display_name = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_name"]

    def __str__(self):
        return self.display_name


class BuddyGroupMember(models.Model):
    uid = models.BigAutoField(primary_key=True)
    group = models.ForeignKey(BuddyGroup, on_delete=models.CASCADE, related_name="members")
    feuser = models.ForeignKey(
        "feusers.FeUser", null=True, blank=True, on_delete=models.CASCADE,
        related_name="group_memberships"
    )
    dummy = models.ForeignKey(
        DummyUser, null=True, blank=True, on_delete=models.CASCADE,
        related_name="group_memberships"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.feuser or self.dummy} in {self.group}"


class BuddyGroupInvite(models.Model):
    """Invitation to join a buddy group. Also establishes a BuddyLink if not already buddies."""
    uid = models.BigAutoField(primary_key=True)
    group = models.ForeignKey(BuddyGroup, on_delete=models.CASCADE, related_name="invites")
    inviting_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="group_invites_sent"
    )
    invitee_email = models.EmailField(db_index=True)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def is_valid(self):
        return timezone.now() < self.expires_at

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Group invite to {self.group} for {self.invitee_email}"


class BuddyLink(models.Model):
    """Confirmed mutual buddy relationship between two actual users.

    Convention: user_a.pk < user_b.pk. Always query with the helper below.
    """

    uid = models.BigAutoField(primary_key=True)
    user_a = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="buddy_links_a"
    )
    user_b = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="buddy_links_b"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user_a", "user_b")]
        ordering = ["created_at"]

    def other(self, feuser):
        return self.user_b if self.user_a_id == feuser.pk else self.user_a

    def __str__(self):
        return f"{self.user_a} <-> {self.user_b}"

    @staticmethod
    def for_user(feuser):
        from django.db.models import Q
        return BuddyLink.objects.filter(Q(user_a=feuser) | Q(user_b=feuser))

    @staticmethod
    def between(feuser_a, feuser_b):
        try:
            lo, hi = sorted([feuser_a, feuser_b], key=lambda u: u.pk)
            return BuddyLink.objects.get(user_a=lo, user_b=hi)
        except BuddyLink.DoesNotExist:
            return None


class BuddyInvite(models.Model):
    uid = models.BigAutoField(primary_key=True)
    inviter = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="buddy_invites_sent"
    )
    invitee_email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

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
        DummyUser, on_delete=models.CASCADE, related_name="merge_invites"
    )
    invited_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="merge_invites_received"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

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
    group set: group join invite (also creates BuddyLink on accept).
    dummy + group set: merge invite for a group dummy.
    Neither set: plain buddy invite.
    """

    uid = models.BigAutoField(primary_key=True)
    inviting_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="onboarding_invites_sent"
    )
    dummy = models.ForeignKey(
        DummyUser, on_delete=models.CASCADE, null=True, blank=True, related_name="onboarding_invites"
    )
    group = models.ForeignKey(
        BuddyGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="onboarding_invites"
    )
    invitee_email = models.EmailField(db_index=True)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

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


class BuddySpending(models.Model):
    """One row per (expense, participant). The expense owner is never a participant here."""

    uid = models.BigAutoField(primary_key=True)
    expense = models.ForeignKey(
        "budget.Expense", on_delete=models.CASCADE, related_name="buddy_spendings"
    )
    participant_feuser = models.ForeignKey(
        "feusers.FeUser",
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="buddy_spending_rows",
    )
    participant_dummy = models.ForeignKey(
        DummyUser,
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="buddy_spending_rows",
    )
    share_percent = models.DecimalField(max_digits=6, decimal_places=3)

    class Meta:
        ordering = ["uid"]

    def __str__(self):
        p = self.participant_feuser or self.participant_dummy
        return f"{p}: {self.share_percent}%"
