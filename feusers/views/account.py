import csv
import io
import zipfile
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone

from ..forms import AISettingsForm, ChangeEmailForm, ChangePasswordForm, ProfileForm
from ..utils import _get_session_feuser


def profile(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    profile_form  = ProfileForm(instance=feuser)
    ai_form       = AISettingsForm(instance=feuser)
    email_form    = ChangeEmailForm(feuser=feuser)
    password_form = ChangePasswordForm(feuser=feuser)
    success       = request.GET.get("success")
    email_error   = None

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
                if settings.DISABLE_EMAILING:
                    feuser.email = new_email
                    feuser.save(update_fields=["email"])
                    return redirect(f"{request.path}?success=email_direct")
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


def account_export(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    from budget.models import Category, Expense, ScheduledExpense, Tag

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # profile.csv — dynamic: all concrete fields except internal security tokens
        _SKIP_FIELDS = {
            "password", "confirmation_token", "password_reset_token",
            "password_reset_expires", "totp_secret", "totp_recovery_hash",
            "email_change_token",
        }
        _MASK_FIELDS = {"anthropic_api_key"}
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["field", "value"])
        for field in feuser._meta.concrete_fields:
            if field.name in _SKIP_FIELDS:
                continue
            value = getattr(feuser, field.name)
            if field.name in _MASK_FIELDS:
                value = ("********" + value[-4:]) if value else ""
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            w.writerow([field.name, value])
        zf.writestr("profile.csv", p.getvalue())

        def _write_model_csv(p, qs, *, skip=(), extra=()):
            """All concrete fields (minus skip), plus extra=(col, fn) M2M columns."""
            fields = [f for f in qs.model._meta.concrete_fields if f.name not in skip]
            w = csv.writer(p)
            w.writerow([f.attname for f in fields] + [col for col, _ in extra])
            for obj in qs:
                row = []
                for field in fields:
                    value = getattr(obj, field.attname)
                    if hasattr(value, "isoformat"):
                        value = value.isoformat()
                    row.append("" if value is None else value)
                for _, fn in extra:
                    row.append(fn(obj))
                w.writerow(row)

        _TAGS     = ("tags",     lambda obj: "|".join(t.title for t in obj.tags.all()))
        _CATEGORY = ("category", lambda obj: obj.category.title if obj.category else "")

        p = io.StringIO()
        _write_model_csv(p, Category.objects.filter(owning_feuser=feuser), skip={"owning_feuser"})
        zf.writestr("categories.csv", p.getvalue())

        p = io.StringIO()
        _write_model_csv(p, Tag.objects.filter(owning_feuser=feuser), skip={"owning_feuser"})
        zf.writestr("tags.csv", p.getvalue())

        p = io.StringIO()
        _write_model_csv(
            p,
            Expense.objects.filter(owning_feuser=feuser)
                .select_related("category").prefetch_related("tags").order_by("date_created"),
            skip={"owning_feuser", "category"},
            extra=[_CATEGORY, _TAGS],
        )
        zf.writestr("expenses.csv", p.getvalue())

        p = io.StringIO()
        _write_model_csv(
            p,
            ScheduledExpense.objects.filter(owning_feuser=feuser)
                .select_related("category").prefetch_related("tags"),
            skip={"owning_feuser", "category"},
            extra=[_CATEGORY, _TAGS],
        )
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


def api_key_generate(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    user = _get_session_feuser(request)
    if not user:
        return redirect("login")
    user.generate_api_key()
    user.save(update_fields=["api_key"])
    return redirect("profile")


def api_key_revoke(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    user = _get_session_feuser(request)
    if not user:
        return redirect("login")
    user.revoke_api_key()
    user.save(update_fields=["api_key"])
    return redirect("profile")
