from django import forms

from .models import FeUser


class ProfileForm(forms.ModelForm):
    class Meta:
        model = FeUser
        fields = ["first_name", "last_name", "currency", "month_start_day", "month_start_prev", "unspent_allowance_action", "email_notifications"]
        labels = {
            "month_start_day": "Month starts on day",
            "month_start_prev": "In the previous calendar month",
            "unspent_allowance_action": "At month end, unspent allowance should",
            "email_notifications": "Send email notifications for upcoming and settled expenses",
        }
        widgets = {
            "month_start_day": forms.NumberInput(attrs={"min": 0, "max": 31}),
        }


class AISettingsForm(forms.ModelForm):
    class Meta:
        model = FeUser
        fields = ["anthropic_api_key", "ai_custom_instructions"]
        labels = {
            "anthropic_api_key": "Anthropic API key",
            "ai_custom_instructions": "Custom instructions",
        }
        widgets = {
            "anthropic_api_key": forms.PasswordInput(render_value=True, attrs={"autocomplete": "off"}),
            "ai_custom_instructions": forms.Textarea(attrs={"rows": 5, "placeholder": "e.g. Always assign groceries to the 'Food' category and tag with 'Rewe' when the payee is Rewe."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        key = self.instance.anthropic_api_key if self.instance and self.instance.pk else ""
        if key:
            self.initial["anthropic_api_key"] = "********" + key[-4:]

    def clean_anthropic_api_key(self):
        value = self.cleaned_data.get("anthropic_api_key", "")
        if value.startswith("*"):
            return self.instance.anthropic_api_key
        return value


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
