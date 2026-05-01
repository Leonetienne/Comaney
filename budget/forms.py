from django import forms
from django.utils import timezone

from .models import Category, Expense, ScheduledExpense, Tag, TransactionType


class ExpenseForm(forms.ModelForm):
    def __init__(self, *args, feuser=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = [c for c in TransactionType.choices if c[0] != TransactionType.CARRY_OVER]
        self.fields["type"].choices = allowed
        if feuser:
            self.fields["category"].queryset = Category.objects.filter(owning_feuser=feuser)
            self.fields["tags"].queryset = Tag.objects.filter(owning_feuser=feuser)
        if not self.initial.get("date_due") and not self.instance.pk:
            self.fields["date_due"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("settled") and not cleaned.get("date_due"):
            self.add_error("date_due", "Due date is required when the expense is not settled.")
        return cleaned

    class Meta:
        model = Expense
        fields = ["title", "payee", "type", "value", "category", "tags", "note", "date_due", "settled", "auto_settle_on_due_date", "deactivated", "notify"]
        widgets = {
            "type": forms.Select(choices=[
                c for c in TransactionType.choices if c[0] != TransactionType.CARRY_OVER
            ]),
            "value": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "note": forms.Textarea(attrs={"rows": 3, "maxlength": 1024}),
            "date_due": forms.DateInput(attrs={"type": "date"}),
            "tags": forms.CheckboxSelectMultiple(),
        }
        labels = {
            "date_due": "Due date",
            "auto_settle_on_due_date": "Auto-settle when reaching due date",
            "deactivated": "Deactivated",
            "notify": "Send email notifications for this expense",
        }


class ScheduledExpenseForm(forms.ModelForm):
    def __init__(self, *args, feuser=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = [c for c in TransactionType.choices if c[0] != TransactionType.CARRY_OVER]
        self.fields["type"].choices = allowed
        if feuser:
            self.fields["category"].queryset = Category.objects.filter(owning_feuser=feuser)
            self.fields["tags"].queryset = Tag.objects.filter(owning_feuser=feuser)
        if not self.instance.pk:
            self.fields["repeat_base_date"].initial = timezone.localdate()

    class Meta:
        model = ScheduledExpense
        fields = [
            "title", "payee", "type", "value",
            "repeat_every_factor", "repeat_every_unit", "repeat_base_date", "end_on",
            "category", "tags", "note", "default_auto_settle_on_due_date", "deactivated", "notify",
        ]
        widgets = {
            "type": forms.Select(choices=[
                c for c in TransactionType.choices if c[0] != TransactionType.CARRY_OVER
            ]),
            "value": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "repeat_base_date": forms.DateInput(attrs={"type": "date"}),
            "end_on": forms.DateInput(attrs={"type": "date"}),
            "repeat_every_factor": forms.NumberInput(attrs={"min": "1"}),
            "note": forms.Textarea(attrs={"rows": 3, "maxlength": 1024}),
            "tags": forms.CheckboxSelectMultiple(),
        }
        labels = {
            "repeat_every_factor": "Every",
            "repeat_every_unit": "Unit",
            "repeat_base_date": "Starting from",
            "end_on": "End on",
            "default_auto_settle_on_due_date": "Auto-settle generated expenses when reaching due date",
            "deactivated": "Deactivated",
            "notify": "Send email notifications for generated expenses",
        }
