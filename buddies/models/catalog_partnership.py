import secrets

from django.db import models


class CatalogPartnership(models.Model):
    """A group of FeUsers who share a synchronized tag and category catalog."""

    uid = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        members = list(self.memberships.select_related("feuser").values_list("feuser__email", flat=True)[:4])
        return f"Partnership({', '.join(members)})"


class CatalogPartnershipMembership(models.Model):
    """One row per member of a CatalogPartnership."""

    partnership = models.ForeignKey(
        CatalogPartnership, on_delete=models.CASCADE, related_name="memberships"
    )
    feuser = models.OneToOneField(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="catalog_membership"
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    onboarding_complete = models.BooleanField(default=False)

    class Meta:
        unique_together = [("partnership", "feuser")]

    def __str__(self):
        state = "complete" if self.onboarding_complete else "onboarding"
        return f"{self.feuser} in Partnership#{self.partnership_id} ({state})"


class CatalogPartnershipInvite(models.Model):
    """Pending invitation to join a CatalogPartnership."""

    STATUS_PENDING = "pending"
    STATUS_IN_SETUP = "in_setup"
    STATUS_ACTIVE = "active"
    STATUS_DECLINED = "declined"
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("in_setup", "In Setup"),
        ("active", "Active"),
        ("declined", "Declined"),
    ]

    partnership = models.ForeignKey(
        CatalogPartnership, on_delete=models.CASCADE, related_name="invites"
    )
    inviter = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="partnership_invites_sent"
    )
    invitee_email = models.EmailField(db_index=True)
    token = models.CharField(max_length=64, unique=True, db_index=True, default=secrets.token_urlsafe)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Partnership invite from {self.inviter} to {self.invitee_email} ({self.status})"
