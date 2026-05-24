from django.db import models
from django.utils import timezone

from .base import OwnedModel, TransactionType


class Expense(OwnedModel):
    title = models.CharField(max_length=128)
    payee = models.CharField(max_length=128, blank=True)
    note = models.TextField(blank=True, max_length=1024)
    category = models.ForeignKey(
        "budget.Category", null=True, blank=True, on_delete=models.SET_NULL, related_name="expenses"
    )
    tags = models.ManyToManyField("budget.Tag", blank=True, related_name="expenses")
    type = models.CharField(max_length=12, choices=TransactionType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    date_due = models.DateField(null=True, blank=True, default=None)
    date_created = models.DateTimeField(auto_now_add=True)
    settled = models.BooleanField(default=True)
    deactivated = models.BooleanField(default=False)
    auto_settle_on_due_date = models.BooleanField(default=False)
    notify = models.BooleanField(default=True, blank=True)
    last_notification_class_sent = models.CharField(max_length=10, blank=True, default="")
    source_scheduled = models.ForeignKey(
        "budget.ScheduledExpense", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="generated_expenses",
    )
    last_mod = models.DateTimeField(default=timezone.now)
    # Buddy fields
    is_dummy = models.BooleanField(default=False)
    is_buddies_settlement = models.BooleanField(default=False)
    buddy_approved = models.BooleanField(default=True)
    upfront_payee_dummy = models.ForeignKey(
        "buddies.DummyUser",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="upfront_expenses",
    )
    project = models.ForeignKey(
        "buddies.Project",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="expenses",
    )

    class Meta:
        ordering = ["-date_created"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            self.last_mod = timezone.now()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = list(update_fields) + ["last_mod"]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title

    @property
    def is_income(self) -> bool:
        return self.type == TransactionType.INCOME

    def _settlement_locked(self) -> bool:
        """
        True when this approved settlement is locked (no further editing/deletion).
        A settlement is locked when approved AND a real user OTHER THAN the owner
        confirmed it as creditor in buddy_spendings. The owner feuser appearing in
        their own buddy_spendings (settlement-from-dummy pattern) does not lock it.
        Settlements with only offline-member creditors are never locked.
        """
        return self.buddy_spendings.filter(
            participant_feuser__isnull=False
        ).exclude(
            participant_feuser_id=self.owning_feuser_id
        ).exists()

    @property
    def settlement_can_delete(self) -> bool:
        if not self.is_buddies_settlement:
            return True
        if not self.buddy_approved:
            return True
        return not self._settlement_locked()

    @property
    def settlement_can_edit(self) -> bool:
        if not self.is_buddies_settlement:
            return True
        if not self.buddy_approved:
            return True
        return not self._settlement_locked()
