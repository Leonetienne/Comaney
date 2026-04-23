from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render

from .forms import LoginForm, PasswordForgotForm, PasswordResetForm, RegistrationForm
from .models import FeUser


def hello_world(request):
    feusers = FeUser.objects.filter(is_active=True, is_confirmed=True)
    return render(request, "feusers/hello_world.html", {"feusers": feusers})


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = FeUser(
                email=form.cleaned_data["email"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                is_confirmed=False,
            )
            user.set_password(form.cleaned_data["password"])
            user.generate_confirmation_token()
            user.save()

            confirm_url = f"{settings.SITE_URL}/confirm/{user.confirmation_token}/"
            send_mail(
                subject="Please confirm your email address",
                message=(
                    f"Hi {user.first_name},\n\n"
                    f"please confirm your Comoney registration:\n\n"
                    f"{confirm_url}\n\n"
                    f"If you didn't sign up, you can safely ignore this email."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
            )
            return redirect("register_success")
    else:
        form = RegistrationForm()

    return render(request, "feusers/register.html", {"form": form})


def register_success(request):
    return render(request, "feusers/register_success.html")


def login_view(request):
    if request.session.get("feuser_id"):
        return redirect("hello_world")

    error = None
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].lower().strip()
            try:
                user = FeUser.objects.get(email=email, is_active=True)
            except FeUser.DoesNotExist:
                user = None

            if user is None or not user.check_password(form.cleaned_data["password"]):
                error = "Invalid email or password."
            elif not user.is_confirmed:
                error = "Please confirm your email address first."
            else:
                request.session["feuser_id"] = user.pk
                return redirect("hello_world")
    else:
        form = LoginForm()

    return render(request, "feusers/login.html", {"form": form, "error": error})


def logout_view(request):
    if request.method == "POST":
        request.session.flush()
    return redirect("hello_world")


def password_forgot(request):
    if request.method == "POST":
        form = PasswordForgotForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].lower().strip()
            try:
                user = FeUser.objects.get(email=email, is_active=True, is_confirmed=True)
                user.generate_password_reset_token()
                user.save(update_fields=["password_reset_token", "password_reset_expires"])
                reset_url = f"{settings.SITE_URL}/password-reset/{user.password_reset_token}/"
                send_mail(
                    subject="Reset your password",
                    message=(
                        f"Hi {user.first_name},\n\n"
                        f"you requested a password reset. Click the link below — it expires in 1 hour:\n\n"
                        f"{reset_url}\n\n"
                        f"If you didn't request this, you can safely ignore this email."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                )
            except FeUser.DoesNotExist:
                pass  # intentional: don't reveal whether the email exists
            return redirect("password_forgot_sent")
    else:
        form = PasswordForgotForm()
    return render(request, "feusers/password_forgot.html", {"form": form})


def password_forgot_sent(request):
    return render(request, "feusers/password_forgot_sent.html")


def password_reset(request, token):
    try:
        user = FeUser.objects.get(password_reset_token=token, is_active=True)
    except FeUser.DoesNotExist:
        return render(request, "feusers/password_reset_invalid.html", status=404)

    if not user.is_password_reset_token_valid():
        return render(request, "feusers/password_reset_invalid.html", status=404)

    if request.method == "POST":
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data["password"])
            user.clear_password_reset_token()
            user.save(update_fields=["password", "password_reset_token", "password_reset_expires"])
            return redirect("password_reset_done")
    else:
        form = PasswordResetForm()
    return render(request, "feusers/password_reset.html", {"form": form})


def password_reset_done(request):
    return render(request, "feusers/password_reset_done.html")


def confirm_email(request, token):
    user = get_object_or_404(FeUser, confirmation_token=token, is_confirmed=False)
    user.is_confirmed = True
    user.is_active = True
    user.confirmation_token = ""
    user.save(update_fields=["is_confirmed", "is_active", "confirmation_token"])
    return render(request, "feusers/confirmed.html", {"user": user})
