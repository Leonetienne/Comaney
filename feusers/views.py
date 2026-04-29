import hashlib
import secrets
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string

from .forms import (
    AISettingsForm, ChangeEmailForm, ChangePasswordForm, LoginForm,
    PasswordForgotForm, PasswordResetForm, ProfileForm, RegistrationForm,
)
from .models import FeUser


def landing_page(request):
    if request.session.get("feuser_id"):
        return redirect("budget:dashboard")
    return render(request, "feusers/landing_page.html", {"active_nav": "home"})


_POW_DIFFICULTY = 18


def _new_pow_challenge(request) -> str:
    challenge = secrets.token_hex(16)
    request.session["pow_challenge"] = challenge
    return challenge


def _check_pow(challenge: str, nonce_str: str) -> bool:
    try:
        nonce = int(nonce_str)
        if nonce < 0:
            return False
    except (ValueError, TypeError):
        return False
    digest = hashlib.sha256(f"{challenge}:{nonce}".encode()).digest()
    bits = _POW_DIFFICULTY
    for byte in digest:
        if bits <= 0:
            break
        if bits >= 8:
            if byte != 0:
                return False
            bits -= 8
        else:
            if byte >> (8 - bits) != 0:
                return False
            break
    return True


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
            # consume challenge — single use
            del request.session["pow_challenge"]
        else:
            pow_error = "Proof-of-work validation failed. Please wait for the puzzle to solve and try again."
        # always issue a fresh challenge for the next attempt
        new_challenge = _new_pow_challenge(request)
        if form.is_valid() and pow_ok:
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
    if not settings.ADMIN_NOTIFICATION_EMAIL or not settings.ENABLE_REGISTRATION:
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
                request.session["feuser_id"] = user.pk
                return redirect("landing_page")
    else:
        form = LoginForm()

    return render(request, "feusers/login.html", {"form": form, "error": error})


def logout_view(request):
    if request.method == "POST":
        request.session.flush()
    return redirect("landing_page")


def _get_session_feuser(request):
    feuser_id = request.session.get("feuser_id")
    if not feuser_id:
        return None
    try:
        return FeUser.objects.get(pk=feuser_id, is_active=True)
    except FeUser.DoesNotExist:
        return None


def profile(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    profile_form    = ProfileForm(instance=feuser)
    ai_form         = AISettingsForm(instance=feuser)
    email_form      = ChangeEmailForm(feuser=feuser)
    password_form   = ChangePasswordForm(feuser=feuser)
    success = request.GET.get("success")
    email_error = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "profile":
            profile_form = ProfileForm(request.POST, instance=feuser)
            if profile_form.is_valid():
                profile_form.save()
                return redirect(f"{request.path}?success=profile")

        elif action == "ai":
            ai_form = AISettingsForm(request.POST, instance=feuser)
            if ai_form.is_valid():
                ai_form.save()
                return redirect(f"{request.path}?success=ai")

        elif action == "email":
            email_form = ChangeEmailForm(request.POST, feuser=feuser)
            if email_form.is_valid():
                new_email = email_form.cleaned_data["email"]
                feuser.generate_email_change_token(new_email)
                feuser.save(update_fields=["pending_email", "email_change_token"])
                confirm_url = f"{settings.SITE_URL}/confirm-email-change/{feuser.email_change_token}/"
                _ctx = {"confirm_url": confirm_url, "first_name": feuser.first_name, "site_url": settings.SITE_URL}
                try:
                    send_mail(
                        subject="Confirm your new email address",
                        message=(
                            f"Hi {feuser.first_name},\n\n"
                            f"please confirm your new email address by clicking the link below:\n\n"
                            f"{confirm_url}\n\n"
                            f"If you didn't request this, you can safely ignore this email."
                        ),
                        html_message=render_to_string("emails/email_change_confirm.html", _ctx),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[new_email],
                    )
                    return redirect(f"{request.path}?success=email")
                except (SMTPException, OSError):
                    feuser.pending_email = ""
                    feuser.email_change_token = ""
                    feuser.save(update_fields=["pending_email", "email_change_token"])
                    email_error = "We couldn't send a confirmation email to that address. Please check it and try again."

        elif action == "password":
            password_form = ChangePasswordForm(request.POST, feuser=feuser)
            if password_form.is_valid():
                feuser.set_password(password_form.cleaned_data["new_password"])
                feuser.save(update_fields=["password"])
                return redirect(f"{request.path}?success=password")

    return render(request, "feusers/profile.html", {
        "active_nav": "profile",
        "profile_form": profile_form,
        "ai_form": ai_form,
        "email_form": email_form,
        "password_form": password_form,
        "success": success,
        "email_error": email_error,
    })


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


def account_export(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    import csv, io, zipfile
    from django.http import HttpResponse
    from django.utils import timezone
    from budget.models import Category, Expense, ScheduledExpense, Tag

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # profile.csv
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["field", "value"])
        key = feuser.anthropic_api_key
        masked_key = ("********" + key[-4:]) if key else ""
        w.writerows([
            ["email",        feuser.email],
            ["first_name",   feuser.first_name],
            ["last_name",    feuser.last_name],
            ["currency",     feuser.currency],
            ["anthropic_api_key", masked_key],
            ["totp_enabled", feuser.totp_enabled],
            ["created_at",   feuser.created_at.isoformat()],
        ])
        zf.writestr("profile.csv", p.getvalue())

        # categories.csv
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["uid", "title"])
        for c in Category.objects.filter(owning_feuser=feuser):
            w.writerow([c.uid, c.title])
        zf.writestr("categories.csv", p.getvalue())

        # tags.csv
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["uid", "title"])
        for t in Tag.objects.filter(owning_feuser=feuser):
            w.writerow([t.uid, t.title])
        zf.writestr("tags.csv", p.getvalue())

        # expenses.csv
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["uid", "title", "type", "value", "payee", "note", "category", "tags", "date_due", "date_created", "settled"])
        for e in Expense.objects.filter(owning_feuser=feuser).select_related("category").prefetch_related("tags").order_by("date_created"):
            w.writerow([
                e.uid, e.title, e.type, e.value, e.payee, e.note,
                e.category.title if e.category else "",
                "|".join(t.title for t in e.tags.all()),
                e.date_due or "", e.date_created.isoformat(), e.settled,
            ])
        zf.writestr("expenses.csv", p.getvalue())

        # scheduled_expenses.csv
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["uid", "title", "type", "value", "payee", "note", "category", "tags", "repeat_base_date", "repeat_every_factor", "repeat_every_unit"])
        for s in ScheduledExpense.objects.filter(owning_feuser=feuser).select_related("category").prefetch_related("tags"):
            w.writerow([
                s.uid, s.title, s.type, s.value, s.payee, s.note,
                s.category.title if s.category else "",
                "|".join(t.title for t in s.tags.all()),
                s.repeat_base_date or "", s.repeat_every_factor or "", s.repeat_every_unit,
            ])
        zf.writestr("scheduled_expenses.csv", p.getvalue())

    filename = f"comaney_export_{timezone.localdate().isoformat()}.zip"
    response = HttpResponse(buf.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def account_delete(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    error = None
    if request.method == "POST":
        password = request.POST.get("password", "")
        if not feuser.check_password(password):
            error = "Incorrect password."
        else:
            request.session.flush()
            feuser.delete()
            return redirect("landing_page")

    return render(request, "feusers/account_delete.html", {"error": error})


def _totp_qr_b64(uri: str) -> str:
    import io, base64, qrcode
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def totp_setup(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    import pyotp
    error = None

    recovery_code = None

    if request.method == "POST":
        code   = request.POST.get("code", "").strip()
        secret = request.session.get("totp_setup_secret", "")
        if not secret:
            return redirect("totp_setup")
        totp = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            raw = secrets.token_hex(5).upper()
            recovery_code = f"{raw[:5]}-{raw[5:]}"
            feuser.totp_secret        = secret
            feuser.totp_enabled       = True
            feuser.totp_recovery_hash = hashlib.sha256(raw.encode()).hexdigest()
            feuser.save(update_fields=["totp_secret", "totp_enabled", "totp_recovery_hash"])
            del request.session["totp_setup_secret"]
            return render(request, "feusers/totp_setup.html", {
                "recovery_code": recovery_code,
                "done": True,
            })
        error = "Invalid code — please try again."
    else:
        secret = pyotp.random_base32()
        request.session["totp_setup_secret"] = secret

    secret = request.session["totp_setup_secret"]
    uri    = pyotp.totp.TOTP(secret).provisioning_uri(feuser.email, issuer_name="Comaney")
    return render(request, "feusers/totp_setup.html", {
        "qr_b64": _totp_qr_b64(uri),
        "secret": secret,
        "error": error,
    })


def totp_disable(request):
    feuser = _get_session_feuser(request)
    if not feuser or not feuser.totp_enabled:
        return redirect("profile")

    import pyotp
    error = None
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        if pyotp.TOTP(feuser.totp_secret).verify(code, valid_window=1):
            feuser.totp_secret  = ""
            feuser.totp_enabled = False
            feuser.save(update_fields=["totp_secret", "totp_enabled"])
            return redirect("profile")
        error = "Invalid code."
    return render(request, "feusers/totp_disable.html", {"error": error})


def totp_verify(request):
    pending_id = request.session.get("totp_pending_id")
    if not pending_id:
        return redirect("login")

    import pyotp
    error = None
    if request.method == "POST":
        try:
            user = FeUser.objects.get(pk=pending_id, is_active=True, totp_enabled=True)
        except FeUser.DoesNotExist:
            return redirect("login")

        code = request.POST.get("code", "").strip()
        if pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
            del request.session["totp_pending_id"]
            request.session["feuser_id"] = user.pk
            return redirect("landing_page")
        error = "Invalid code — please try again."

    return render(request, "feusers/totp_verify.html", {"error": error})


def totp_verify_recovery(request):
    pending_id = request.session.get("totp_pending_id")
    if not pending_id:
        return redirect("login")

    error = None
    if request.method == "POST":
        try:
            user = FeUser.objects.get(pk=pending_id, is_active=True, totp_enabled=True)
        except FeUser.DoesNotExist:
            return redirect("login")

        recovery = request.POST.get("recovery", "").strip().upper().replace("-", "")
        digest   = hashlib.sha256(recovery.encode()).hexdigest()
        if user.totp_recovery_hash and secrets.compare_digest(digest, user.totp_recovery_hash):
            user.totp_secret        = ""
            user.totp_enabled       = False
            user.totp_recovery_hash = ""
            user.save(update_fields=["totp_secret", "totp_enabled", "totp_recovery_hash"])
            del request.session["totp_pending_id"]
            request.session["feuser_id"] = user.pk
            return redirect("landing_page")
        error = "Invalid recovery code."

    return render(request, "feusers/totp_verify.html", {"error": error, "recovery_mode": True})


def confirm_email(request, token):
    user = get_object_or_404(FeUser, confirmation_token=token, is_confirmed=False)
    user.is_confirmed = True
    user.is_active = True
    user.confirmation_token = ""
    user.save(update_fields=["is_confirmed", "is_active", "confirmation_token"])
    from budget.fixtures import create_defaults
    create_defaults(user)
    return render(request, "feusers/confirmed.html", {"user": user})


def _require_login(request):
    feuser_id = request.session.get("feuser_id")
    if not feuser_id:
        return None
    try:
        return FeUser.objects.get(pk=feuser_id, is_active=True)
    except FeUser.DoesNotExist:
        return None


def api_key_generate(request):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])
    user = _require_login(request)
    if not user:
        return redirect("login")
    user.generate_api_key()
    user.save(update_fields=["api_key"])
    return redirect("profile")


def api_key_revoke(request):
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])
    user = _require_login(request)
    if not user:
        return redirect("login")
    user.revoke_api_key()
    user.save(update_fields=["api_key"])
    return redirect("profile")
