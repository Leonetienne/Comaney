from django import forms

from .models import FeUser


class ProfileForm(forms.ModelForm):
    class Meta:
        model = FeUser
        fields = ["first_name", "last_name", "currency", "anthropic_api_key"]
        labels = {"anthropic_api_key": "Anthropic API key"}
        widgets = {"anthropic_api_key": forms.PasswordInput(render_value=True, attrs={"autocomplete": "off"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        key = self.instance.anthropic_api_key if self.instance and self.instance.pk else ""
        if key:
            # Send only a fixed mask + last 4 chars — the real key never reaches the frontend
            self.initial["anthropic_api_key"] = "********" + key[-4:]

    def clean_anthropic_api_key(self):
        value = self.cleaned_data.get("anthropic_api_key", "")
        if value.startswith("*"):
            # Masked placeholder submitted — keep the existing key unchanged
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
