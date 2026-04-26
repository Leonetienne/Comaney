from django.db import models

from feusers.models import FeUser


class TransactionType(models.TextChoices):
    INCOME = "income", "Income"
    EXPENSE = "expense", "Expense"
    SAVINGS_DEPOSIT = "savings_dep", "Savings Deposit"
    SAVINGS_WITHDRAWAL = "savings_wit", "Savings Withdrawal"


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
    title = models.CharField(max_length=255)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class Tag(OwnedModel):
    title = models.CharField(max_length=255)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class Expense(OwnedModel):
    title = models.CharField(max_length=255)
    payee = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="expenses"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="expenses")
    type = models.CharField(max_length=12, choices=TransactionType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    date_due = models.DateField(null=True, blank=True, default=None)
    date_created = models.DateTimeField(auto_now_add=True)
    settled = models.BooleanField(default=True)
    auto_settle_on_due_date = models.BooleanField(default=False)
    source_scheduled = models.ForeignKey(
        "ScheduledExpense", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="generated_expenses",
    )

    class Meta:
        ordering = ["-date_created"]

    def __str__(self) -> str:
        return self.title

    @property
    def is_income(self) -> bool:
        return self.type == TransactionType.INCOME


class ScheduledExpense(OwnedModel):
    title = models.CharField(max_length=255)
    payee = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="scheduled_expenses"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="scheduled_expenses")
    type = models.CharField(max_length=12, choices=TransactionType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    default_settled = models.BooleanField(default=True)
    default_auto_settle_on_due_date = models.BooleanField(default=False)
    repeat_base_date = models.DateField(null=True, blank=True)
    repeat_every_factor = models.PositiveIntegerField(null=True, blank=True)
    repeat_every_unit = models.CharField(max_length=10, choices=RepeatUnit.choices, blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title

    @property
    def is_income(self) -> bool:
        return self.type == TransactionType.INCOME
