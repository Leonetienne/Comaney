from datetime import timedelta

from django.db import models
from django.utils import timezone


class BuddySpending(models.Model):
    """One row per (expense, participant). The expense owner is never a participant here."""

    APPROVAL_NEUTRAL = 0
    APPROVAL_APPROVED = 1
    APPROVAL_REJECTED = 2

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
        "buddies.DummyUser",
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="buddy_spending_rows",
    )
    share_percent = models.DecimalField(max_digits=6, decimal_places=3)
    approval_state = models.SmallIntegerField(default=0)
    consent_set_at = models.DateTimeField(null=True, blank=True)
    last_mod = models.DateTimeField(default=timezone.now)

    @property
    def consent_locked(self) -> bool:
        """True once the 24-hour change window after first consent has elapsed."""
        if self.consent_set_at is None:
            return False
        return timezone.now() > self.consent_set_at + timedelta(hours=24)

    @property
    def can_change_consent(self) -> bool:
        """True when the participant may still change their decision.

        A rejected state is always changeable; only revoking an approval is
        time-restricted to 24 h after the first decision.
        """
        if self.approval_state == self.APPROVAL_REJECTED:
            return True
        return not self.consent_locked

    class Meta:
        ordering = ["uid"]

    def __str__(self):
        p = self.participant_feuser or self.participant_dummy
        return f"{p}: {self.share_percent}%"
