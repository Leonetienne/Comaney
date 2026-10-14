from django import forms

from ai_providers import get_provider

from . import ai_user_config
from .models import FeUser


class ProfileForm(forms.ModelForm):
    class Meta:
        model = FeUser
        fields = ["first_name", "last_name", "currency", "month_start_day", "month_start_prev", "unspent_allowance_action"]
        labels = {
            "month_start_day": "Month starts on day",
            "month_start_prev": "In the previous calendar month",
            "unspent_allowance_action": "At month end, unspent allowance should",
        }
        widgets = {
            "month_start_day": forms.NumberInput(attrs={"min": 1, "max": 31}),
        }

    def clean_month_start_day(self):
        day = self.cleaned_data.get("month_start_day")
        if day is not None and not (1 <= day <= 31):
            raise forms.ValidationError("Month start day must be between 1 and 31.")
        return day


class NotificationPreferencesForm(forms.ModelForm):
    class Meta:
        model = FeUser
        fields = [
            "email_notifications",
            "notify_expense_reminders",
            "notify_expense_settled",
            "notify_expense_participation",
            "notify_expense_assignments",
            "notify_participant_decisions",
            "notify_settlements",
            "notify_group_activity",
            "notify_own_partnership_changes",
            "notify_someones_partnership_changes",
        ]
        labels = {
            "email_notifications":                  "Enable email notifications",
            "notify_expense_reminders":             "Expense due date reminders (upcoming and overdue)",
            "notify_expense_settled":               "Expense marked as paid",
            "notify_expense_participation":         "Added to, updated in, or removed from a shared expense",
            "notify_expense_assignments":           "A shared expense was assigned to you as upfront payer",
            "notify_participant_decisions":         "A participant approved or rejected your shared expense",
            "notify_settlements":                   "Settlement requests and confirmations",
            "notify_group_activity":                "Project membership changes",
            "notify_own_partnership_changes":       "Catalog Partnership: events that affect you (invites, being kicked)",
            "notify_someones_partnership_changes":  "Catalog Partnership: activity from others (partner joined, left, or removed)",
        }


class AISettingsForm(forms.ModelForm):
    """AI card of the profile. Besides the plain model fields it carries the
    active provider's own user settings, one form field per ConfigField of
    get_user_fields() (named "ai_<key>", see feusers/ai_user_config.py).
    Extra fields exist only for an active provider with user fields."""

    class Meta:
        model = FeUser
        fields = ["disable_ai_ui", "ai_custom_instructions"]
        labels = {
            "disable_ai_ui": "Hide all AI features",
            "ai_custom_instructions": "Custom instructions",
        }
        widgets = {
            "ai_custom_instructions": forms.Textarea(attrs={
                "rows": 5,
                "maxlength": 4096,
                "placeholder": "e.g. Always assign groceries to the 'Food' category and tag with 'Rewe' when the payee is Rewe.",
                "autocomplete": "off",
                "data-lpignore": "true",
                "data-1p-ignore": "true",
                "data-bwignore": "true",
                "data-form-type": "other",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.provider = get_provider()
        self.user_fields = self.provider.get_user_fields() if self.provider else []
        initial = ai_user_config.initial_values(self.provider, self.instance.ai_user_config) if self.user_fields else {}
        # own settings sit between the checkbox and the custom instructions
        instructions = self.fields.pop("ai_custom_instructions")
        for f in self.user_fields:
            name = ai_user_config.form_field_name(f)
            if name in self.fields:
                raise ValueError(f"AI user field {f.key!r} clashes with the form field {name!r}")
            self.fields[name] = ai_user_config.form_field(f)
            self.initial[name] = initial.get(f.key, "")
        self.fields["ai_custom_instructions"] = instructions

    def clean(self):
        cleaned = super().clean()
        self.ai_entry = {}
        if not self.user_fields:
            return cleaned
        submitted = {f.key: self.data.get(ai_user_config.form_field_name(f), "") for f in self.user_fields}
        self.ai_entry, errors = ai_user_config.clean_submission(self.provider, submitted, self.instance.ai_user_config)
        for key, message in errors.items():
            if key == ai_user_config.NON_FIELD:
                self.add_error(None, message)
            else:
                self.add_error(ai_user_config.FIELD_PREFIX + key, message)
        return cleaned

    def save(self, commit=True):
        if self.provider:
            # writes only the active provider's entry (none without user fields); any other is dropped
            self.instance.ai_user_config = ai_user_config.with_entry(self.provider.get_name(), self.ai_entry)
        return super().save(commit=commit)


class AdvancedSettingsForm(forms.ModelForm):
    class Meta:
        model = FeUser
        fields = ["enable_early_access", "show_record_ids"]
        labels = {
            "enable_early_access": "Enable early access features",
            "show_record_ids": "Show record IDs (#123) on expenses and recurring expenses",
        }


class ExpenseEntrySettingsForm(forms.ModelForm):
    class Meta:
        model = FeUser
        fields = ["warn_unclassified_on_save"]
        labels = {
            "warn_unclassified_on_save": "Warn me when saving an expense without a category or tags",
        }


class ChangeEmailForm(forms.Form):
    email = forms.EmailField(label="New email address")
    password = forms.CharField(label="Current password", widget=forms.PasswordInput)

    def __init__(self, *args, feuser=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._feuser = feuser

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if FeUser.objects.filter(email=email).exclude(pk=self._feuser.pk).exists():
            raise forms.ValidationError("This email address is already taken.")
        return email

    def clean_password(self):
        pw = self.cleaned_data["password"]
        if self._feuser and not self._feuser.check_password(pw):
            raise forms.ValidationError("Incorrect password.")
        return pw


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(label="Current password", widget=forms.PasswordInput)
    new_password = forms.CharField(label="New password", widget=forms.PasswordInput)
    new_password_confirm = forms.CharField(label="Repeat new password", widget=forms.PasswordInput)

    def __init__(self, *args, feuser=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._feuser = feuser

    def clean_current_password(self):
        pw = self.cleaned_data["current_password"]
        if self._feuser and not self._feuser.check_password(pw):
            raise forms.ValidationError("Incorrect password.")
        return pw

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("new_password")
        pw2 = cleaned.get("new_password_confirm")
        if pw and pw2 and pw != pw2:
            self.add_error("new_password_confirm", "Passwords do not match.")
        return cleaned


class PasswordForgotForm(forms.Form):
    email = forms.EmailField(label="Email address")


class PasswordResetForm(forms.Form):
    password = forms.CharField(label="New password", widget=forms.PasswordInput)
    password_confirm = forms.CharField(label="Repeat password", widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("password")
        pw_confirm = cleaned.get("password_confirm")
        if pw and pw_confirm and pw != pw_confirm:
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned


class LoginForm(forms.Form):
    email = forms.EmailField(label="Email address")
    password = forms.CharField(label="Password", widget=forms.PasswordInput)


class RegistrationForm(forms.Form):
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150)
    email = forms.EmailField(label="Email address")
    password = forms.CharField(label="Password", widget=forms.PasswordInput)
    password_confirm = forms.CharField(label="Repeat password", widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if FeUser.objects.filter(email=email).exists():
            raise forms.ValidationError("This email address is already taken.")
        return email

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("password")
        pw_confirm = cleaned.get("password_confirm")
        if pw and pw_confirm and pw != pw_confirm:
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned
