from django import forms
from django.utils import timezone

from .models import Category, Expense, ScheduledExpense, Tag, TransactionType


class ExpenseForm(forms.ModelForm):
    def __init__(self, *args, feuser=None, **kwargs):
        super().__init__(*args, **kwargs)
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
        fields = ["title", "payee", "type", "value", "category", "tags", "note", "date_due", "settled"]
        widgets = {
            "type": forms.Select(choices=TransactionType.choices),
            "value": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "note": forms.Textarea(attrs={"rows": 3}),
            "date_due": forms.DateInput(attrs={"type": "date"}),
            "tags": forms.SelectMultiple(),
        }
        labels = {
            "date_due": "Due date",
        }


class ScheduledExpenseForm(forms.ModelForm):
    def __init__(self, *args, feuser=None, **kwargs):
        super().__init__(*args, **kwargs)
        if feuser:
            self.fields["category"].queryset = Category.objects.filter(owning_feuser=feuser)
            self.fields["tags"].queryset = Tag.objects.filter(owning_feuser=feuser)
        if not self.instance.pk:
            self.fields["repeat_base_date"].initial = timezone.localdate()

    class Meta:
        model = ScheduledExpense
        fields = [
            "title", "type", "value",
            "repeat_every_factor", "repeat_every_unit", "repeat_base_date",
            "category", "tags", "note", "default_settled",
        ]
        widgets = {
            "type": forms.Select(choices=TransactionType.choices),
            "value": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "repeat_base_date": forms.DateInput(attrs={"type": "date"}),
            "repeat_every_factor": forms.NumberInput(attrs={"min": "1"}),
            "note": forms.Textarea(attrs={"rows": 3}),
            "tags": forms.SelectMultiple(),
        }
        labels = {
            "repeat_every_factor": "Every",
            "repeat_every_unit": "Unit",
            "repeat_base_date": "Starting from",
            "default_settled": "Mark generated expenses as settled by default",
        }
