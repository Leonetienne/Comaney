from django import forms

from .models import FeUser


class PasswordForgotForm(forms.Form):
    email = forms.EmailField(label="E-Mail-Adresse")


class PasswordResetForm(forms.Form):
    password = forms.CharField(label="Neues Passwort", widget=forms.PasswordInput)
    password_confirm = forms.CharField(label="Passwort wiederholen", widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("password")
        pw_confirm = cleaned.get("password_confirm")
        if pw and pw_confirm and pw != pw_confirm:
            self.add_error("password_confirm", "Die Passwörter stimmen nicht überein.")
        return cleaned


class LoginForm(forms.Form):
    email = forms.EmailField(label="E-Mail-Adresse")
    password = forms.CharField(label="Passwort", widget=forms.PasswordInput)


class RegistrationForm(forms.Form):
    first_name = forms.CharField(label="Vorname", max_length=150)
    last_name = forms.CharField(label="Nachname", max_length=150)
    email = forms.EmailField(label="E-Mail-Adresse")
    password = forms.CharField(label="Passwort", widget=forms.PasswordInput)
    password_confirm = forms.CharField(label="Passwort wiederholen", widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if FeUser.objects.filter(email=email).exists():
            raise forms.ValidationError("Diese E-Mail-Adresse ist bereits vergeben.")
        return email

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get("password")
        pw_confirm = cleaned.get("password_confirm")
        if pw and pw_confirm and pw != pw_confirm:
            self.add_error("password_confirm", "Die Passwörter stimmen nicht überein.")
        return cleaned
