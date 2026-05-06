from smtplib import SMTPException

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string

from ..forms import LoginForm, PasswordForgotForm, PasswordResetForm, RegistrationForm
from ..models import FeUser
from ..utils import _POW_DIFFICULTY, _check_pow, _new_pow_challenge, _record_login


def landing_page(request):
    if request.session.get("feuser_id"):
        return redirect("budget:dashboard")
    return render(request, "feusers/landing_page.html", {"active_nav": "home"})


def register(request):
    if not settings.ENABLE_REGISTRATION:
        from django.http import Http404
        raise Http404
    pow_error = None
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        challenge = request.session.get("pow_challenge", "")
        nonce = request.POST.get("pow_nonce", "")
        pow_ok = challenge and _check_pow(challenge, nonce)
        if pow_ok:
            del request.session["pow_challenge"]
        else:
            pow_error = "Proof-of-work validation failed. Please wait for the puzzle to solve and try again."
        new_challenge = _new_pow_challenge(request)
        if form.is_valid() and pow_ok:
            if settings.DISABLE_EMAILING:
                user = FeUser(
                    email=form.cleaned_data["email"],
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                    is_confirmed=True,
                    is_active=True,
                )
                user.set_password(form.cleaned_data["password"])
                user.save()
                from budget.fixtures import create_defaults
                create_defaults(user)
                request.session["feuser_id"] = user.pk
                return redirect("budget:dashboard")

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
            _ctx = {"confirm_url": confirm_url, "first_name": user.first_name, "site_url": settings.SITE_URL}
            try:
                send_mail(
                    subject="Please confirm your email address",
                    message=(
                        f"Hi {user.first_name},\n\n"
                        f"please confirm your Comaney registration:\n\n"
                        f"{confirm_url}\n\n"
                        f"If you didn't sign up, you can safely ignore this email."
                    ),
                    html_message=render_to_string("emails/registration_confirm.html", _ctx),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                )
            except (SMTPException, OSError):
                user.delete()
                return render(request, "feusers/register.html", {
                    "form": form,
                    "pow_challenge": _new_pow_challenge(request),
                    "pow_difficulty": _POW_DIFFICULTY,
                    "email_error": "We couldn't send a confirmation email to that address. Please check it and try again.",
                })
            return redirect("register_success")
        challenge = new_challenge
    else:
        form = RegistrationForm()
        challenge = _new_pow_challenge(request)

    return render(request, "feusers/register.html", {
        "form": form,
        "pow_challenge": challenge,
        "pow_difficulty": _POW_DIFFICULTY,
        "pow_error": pow_error,
    })


def register_success(request):
    if not settings.ENABLE_REGISTRATION:
        from django.http import Http404
        raise Http404
    return render(request, "feusers/register_success.html")


def contact(request):
    from django.http import Http404
    if not settings.ADMIN_NOTIFICATION_EMAIL or not settings.ENABLE_REGISTRATION or settings.DISABLE_EMAILING:
        raise Http404

    feuser_id = request.session.get("feuser_id")
    logged_in_user = None
    if feuser_id:
        try:
            logged_in_user = FeUser.objects.get(pk=feuser_id, is_active=True)
        except FeUser.DoesNotExist:
            pass

    pow_error = None
    sent = request.GET.get("sent") == "1"
    errors: dict[str, str] = {}

    if request.method == "POST":
        name    = request.POST.get("name", "").strip()
        email   = request.POST.get("email", "").strip()
        subject = request.POST.get("subject", "").strip()
        message = request.POST.get("message", "").strip()

        challenge = request.session.get("pow_challenge", "")
        nonce     = request.POST.get("pow_nonce", "")
        pow_ok    = challenge and _check_pow(challenge, nonce)
        if pow_ok:
            del request.session["pow_challenge"]
        else:
            pow_error = "Proof-of-work validation failed. Please wait for the captcha to solve and try again."
        new_challenge = _new_pow_challenge(request)

        if not name:    errors["name"]    = "Name is required."
        if not email:   errors["email"]   = "Email address is required."
        if not subject: errors["subject"] = "Subject is required."
        if not message: errors["message"] = "Message is required."

        send_error = None
        if pow_ok and not errors:
            user_line = (
                f"{logged_in_user.email} (id={logged_in_user.pk})"
                if logged_in_user else "Not logged in"
            )
            body = (
                f"Name:    {name}\n"
                f"Email:   {email}\n"
                f"Account: {user_line}\n\n"
                f"Subject: {subject}\n\n"
                f"{message}\n"
            )
            html_body = render_to_string("emails/contact.html", {
                "site_url": settings.SITE_URL,
                "contact_name": name,
                "contact_email": email,
                "account_info": (
                    f"{logged_in_user.email} (id={logged_in_user.pk})"
                    if logged_in_user else "Not logged in"
                ),
                "contact_subject": subject,
                "contact_message": message,
            })
            try:
                send_mail(
                    subject=f"[Comaney Contact] {subject}",
                    message=body,
                    html_message=html_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.ADMIN_NOTIFICATION_EMAIL],
                )
            except (SMTPException, OSError):
                send_error = "Could not send your message right now. Please try again later."

            if not send_error:
                return redirect(f"{request.path}?sent=1")

        return render(request, "feusers/contact.html", {
            "name": name, "email": email, "subject": subject, "message": message,
            "pow_challenge": new_challenge,
            "pow_difficulty": _POW_DIFFICULTY,
            "pow_error": pow_error,
            "errors": errors,
            "send_error": send_error,
            "sent": False,
            "logged_in_user": logged_in_user,
        })

    challenge = _new_pow_challenge(request)
    return render(request, "feusers/contact.html", {
        "name":    logged_in_user.first_name + " " + logged_in_user.last_name if logged_in_user else "",
        "email":   logged_in_user.email if logged_in_user else "",
        "subject": "", "message": "",
        "pow_challenge": challenge,
        "pow_difficulty": _POW_DIFFICULTY,
        "pow_error": None,
        "errors": {},
        "sent": sent,
        "logged_in_user": logged_in_user,
    })


def login_view(request):
    if request.session.get("feuser_id"):
        return redirect("landing_page")

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
            elif user.totp_enabled:
                request.session["totp_pending_id"] = user.pk
                return redirect("totp_verify")
            else:
                _record_login(user)
                request.session["feuser_id"] = user.pk
                return redirect("landing_page")
    else:
        form = LoginForm()

    return render(request, "feusers/login.html", {"form": form, "error": error})


def logout_view(request):
    if request.method == "POST":
        request.session.flush()
    return redirect("landing_page")


def confirm_email(request, token):
    user = get_object_or_404(FeUser, confirmation_token=token, is_confirmed=False)
    user.is_confirmed = True
    user.is_active = True
    user.confirmation_token = ""
    user.save(update_fields=["is_confirmed", "is_active", "confirmation_token"])
    from budget.fixtures import create_defaults
    create_defaults(user)
    admin_email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "")
    if admin_email and not settings.DISABLE_EMAILING:
        try:
            _ctx = {"first_name": user.first_name, "last_name": user.last_name, "email": user.email, "site_url": settings.SITE_URL}
            send_mail(
                subject="New user registered",
                message=f"New user: {user.first_name} {user.last_name} <{user.email}>",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[admin_email],
                html_message=render_to_string("emails/new_user_registered.html", _ctx),
                fail_silently=True,
            )
        except Exception:
            pass
    return render(request, "feusers/confirmed.html", {"user": user})


def password_forgot(request):
    if settings.DISABLE_EMAILING:
        return render(request, "feusers/password_forgot.html", {"emailing_disabled": True})
    if request.method == "POST":
        form = PasswordForgotForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].lower().strip()
            try:
                user = FeUser.objects.get(email=email, is_active=True, is_confirmed=True)
                user.generate_password_reset_token()
                user.save(update_fields=["password_reset_token", "password_reset_expires"])
                reset_url = f"{settings.SITE_URL}/password-reset/{user.password_reset_token}/"
                _ctx = {"reset_url": reset_url, "first_name": user.first_name, "site_url": settings.SITE_URL}
                try:
                    send_mail(
                        subject="Reset your password",
                        message=(
                            f"Hi {user.first_name},\n\n"
                            f"you requested a password reset. Click the link below — it expires in 1 hour:\n\n"
                            f"{reset_url}\n\n"
                            f"If you didn't request this, you can safely ignore this email."
                        ),
                        html_message=render_to_string("emails/password_reset.html", _ctx),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                    )
                except (SMTPException, OSError):
                    return render(request, "feusers/password_forgot.html", {
                        "form": form,
                        "email_error": "We couldn't send an email to that address. Please check it and try again.",
                    })
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


def confirm_email_change(request, token):
    user = get_object_or_404(FeUser, email_change_token=token)
    user.email = user.pending_email
    user.pending_email = ""
    user.email_change_token = ""
    user.save(update_fields=["email", "pending_email", "email_change_token"])
    return render(request, "feusers/email_change_confirmed.html", {"user": user})
