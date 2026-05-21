from django.db import models

from feusers.models import FeUser


class TransactionType(models.TextChoices):
    INCOME = "income", "Income"
    EXPENSE = "expense", "Expense"
    SAVINGS_DEPOSIT = "savings_dep", "Savings Deposit"
    SAVINGS_WITHDRAWAL = "savings_wit", "Savings Withdrawal"
    CARRY_OVER = "carry_over", "Carry-Over"


class RepeatUnit(models.TextChoices):
    DAYS = "days", "Days"
    WEEKS = "weeks", "Weeks"
    MONTHS = "months", "Months"
    YEARS = "years", "Years"


class OwnedModel(models.Model):
    uid = models.BigAutoField(primary_key=True)
    owning_feuser = models.ForeignKey(FeUser, on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True


class Category(OwnedModel):
    title = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class Tag(OwnedModel):
    title = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class Expense(OwnedModel):
    title = models.CharField(max_length=128)
    payee = models.CharField(max_length=128, blank=True)
    note = models.TextField(blank=True, max_length=1024)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="expenses"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="expenses")
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
        "ScheduledExpense", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="generated_expenses",
    )
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


class ScheduledExpense(OwnedModel):
    title = models.CharField(max_length=128)
    payee = models.CharField(max_length=128, blank=True)
    note = models.TextField(blank=True, max_length=1024)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="scheduled_expenses"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="scheduled_expenses")
    type = models.CharField(max_length=12, choices=TransactionType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    default_auto_settle_on_due_date = models.BooleanField(default=False)
    repeat_base_date = models.DateField(null=True, blank=True)
    end_on = models.DateField(null=True, blank=True)
    repeat_every_factor = models.PositiveIntegerField(null=True, blank=True)
    repeat_every_unit = models.CharField(max_length=10, choices=RepeatUnit.choices, blank=True)
    deactivated = models.BooleanField(default=False)
    notify = models.BooleanField(default=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title

    @property
    def is_income(self) -> bool:
        return self.type == TransactionType.INCOME


class ExpenseDataOverlay(models.Model):
    """
    Per-participant personal category/tags for a buddy expense.
    The owner's tags/category live on the Expense itself; participants
    and ex-owners use this table to keep their own bookkeeping metadata.
    Invariant: never stored empty — delete instead of zeroing all fields.
    note=None means "inherit the expense's own note"; a non-null note overrides it.
    """
    expense = models.ForeignKey(
        Expense, on_delete=models.CASCADE, related_name="data_overlays"
    )
    feuser = models.ForeignKey(
        FeUser, on_delete=models.CASCADE, related_name="expense_data_overlays"
    )
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL
    )
    tags = models.ManyToManyField(Tag, blank=True)
    note = models.TextField(blank=True, null=True, max_length=1024, default=None)

    class Meta:
        unique_together = [("expense", "feuser")]


class DashboardCard(OwnedModel):
    yaml_config = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self) -> str:
        return f"DashboardCard #{self.pk}"
