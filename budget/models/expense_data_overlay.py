from django.db import models
from django.utils import timezone


class ExpenseDataOverlay(models.Model):
    """
    Per-participant personal category/tags for a buddy expense.
    The owner's tags/category live on the Expense itself; participants
    and ex-owners use this table to keep their own bookkeeping metadata.
    Invariant: never stored empty — delete instead of zeroing all fields.
    note=None means "inherit the expense's own note"; a non-null note overrides it.
    """
    expense = models.ForeignKey(
        "budget.Expense", on_delete=models.CASCADE, related_name="data_overlays"
    )
    feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="expense_data_overlays"
    )
    category = models.ForeignKey(
        "budget.Category", null=True, blank=True, on_delete=models.SET_NULL
    )
    tags = models.ManyToManyField("budget.Tag", blank=True)
    note = models.TextField(blank=True, null=True, max_length=1024, default=None)
    last_mod = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("expense", "feuser")]

    def update_lastmod(self) -> None:
        self.last_mod = timezone.now()
        self.save(update_fields=["last_mod"])
