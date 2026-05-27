from django.db import models
from django.utils import timezone

from .base import OwnedModel, TransactionType, RepeatUnit


class ScheduledExpense(OwnedModel):
    title = models.CharField(max_length=128)
    payee = models.CharField(max_length=128, blank=True)
    note = models.TextField(blank=True, max_length=1024)
    category = models.ForeignKey(
        "budget.Category", null=True, blank=True, on_delete=models.SET_NULL, related_name="scheduled_expenses"
    )
    tags = models.ManyToManyField("budget.Tag", blank=True, related_name="scheduled_expenses")
    type = models.CharField(max_length=12, choices=TransactionType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    default_auto_settle_on_due_date = models.BooleanField(default=False)
    repeat_base_date = models.DateField(null=True, blank=True)
    end_on = models.DateField(null=True, blank=True)
    repeat_every_factor = models.PositiveIntegerField(null=True, blank=True)
    repeat_every_unit = models.CharField(max_length=10, choices=RepeatUnit.choices, blank=True)
    deactivated = models.BooleanField(default=False)
    notify = models.BooleanField(default=True, blank=True)
    last_run = models.PositiveIntegerField(null=True, blank=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)
    last_mod = models.DateTimeField(default=timezone.now)
    # Expense assignment (mirrors the buddy fields on Expense)
    assign_buddy_mode = models.CharField(max_length=10, blank=True, default='')  # '' | 'single' | 'group'
    assign_upfront_type = models.CharField(max_length=10, blank=True, default='me')  # 'me' | 'feuser' | 'dummy'
    assign_upfront_feuser = models.ForeignKey(
        "feusers.FeUser", null=True, blank=True, on_delete=models.SET_NULL,
        related_name='scheduled_assign_upfront',
    )
    assign_upfront_dummy = models.ForeignKey(
        'buddies.DummyUser', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='scheduled_assign_upfront_dummy',
    )
    assign_project = models.ForeignKey(
        'buddies.Project', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='scheduled_expenses',
    )
    assign_spendings_json = models.TextField(blank=True, default='[]')

    class Meta:
        ordering = ["title"]

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
