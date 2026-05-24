import csv
import io
import re
import zipfile
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone

from ..forms import AISettingsForm, ChangeEmailForm, ChangePasswordForm, NotificationPreferencesForm, ProfileForm
from ..utils import _get_session_feuser


def _sanitize_css(value: str) -> str:
    """Strip characters that are not needed for CSS property declarations."""
    return re.sub(r'[<>{}&@`\\]', '', value)


def profile(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    profile_form        = ProfileForm(instance=feuser)
    notifications_form  = NotificationPreferencesForm(instance=feuser)
    ai_form             = AISettingsForm(instance=feuser)
    email_form          = ChangeEmailForm(feuser=feuser)
    password_form       = ChangePasswordForm(feuser=feuser)
    success             = request.GET.get("success")
    email_error         = None
    picture_error       = None
    backdrop_error      = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "picture":
            upload = request.FILES.get("profile_picture")
            if not upload:
                picture_error = "No file selected."
            elif upload.size > 5 * 1024 * 1024:
                picture_error = "File too large. Maximum size is 5 MB."
            else:
                try:
                    from PIL import Image, ImageOps
                    img = Image.open(upload)
                    img.verify()
                    upload.seek(0)
                    img = Image.open(upload)
                    img = ImageOps.fit(img, (256, 256), Image.LANCZOS)
                    if img.mode in ("RGBA", "P", "LA"):
                        img = img.convert("RGB")
                    ppics_dir = settings.MEDIA_ROOT / "ppics"
                    ppics_dir.mkdir(exist_ok=True)
                    img.save(ppics_dir / f"{feuser.pk}.jpg", "JPEG", quality=85)
                    feuser.profile_picture = True
                    feuser.last_mod = timezone.now()
                    feuser.save(update_fields=["profile_picture", "last_mod"])
                    return redirect(f"{request.path}?success=picture")
                except Exception:
                    picture_error = "Could not process the image. Please upload a valid image file."

        elif action == "picture_delete":
            ppic_path = settings.MEDIA_ROOT / "ppics" / f"{feuser.pk}.jpg"
            if ppic_path.exists():
                ppic_path.unlink()
            feuser.profile_picture = False
            feuser.last_mod = timezone.now()
            feuser.save(update_fields=["profile_picture", "last_mod"])
            return redirect(f"{request.path}?success=picture_deleted")

        elif action == "backdrop":
            upload = request.FILES.get("custom_backdrop")
            if not upload:
                backdrop_error = "No file selected."
            elif upload.size > 20 * 1024 * 1024:
                backdrop_error = "File too large. Maximum size is 20 MB."
            else:
                try:
                    from PIL import Image
                    img = Image.open(upload)
                    img.verify()
                    upload.seek(0)
                    img = Image.open(upload)
                    backdrops_dir = settings.MEDIA_ROOT / "backdrops"
                    backdrops_dir.mkdir(exist_ok=True)
                    img.save(backdrops_dir / f"{feuser.pk}.png", "PNG")
                    feuser.custom_backdrop = True
                    feuser.last_mod = timezone.now()
                    feuser.save(update_fields=["custom_backdrop", "last_mod"])
                    return redirect(f"{request.path}?success=backdrop")
                except Exception:
                    backdrop_error = "Could not process the image. Please upload a valid image file."

        elif action == "backdrop_delete":
            backdrop_path = settings.MEDIA_ROOT / "backdrops" / f"{feuser.pk}.png"
            if backdrop_path.exists():
                backdrop_path.unlink()
            feuser.custom_backdrop = False
            feuser.last_mod = timezone.now()
            feuser.save(update_fields=["custom_backdrop", "last_mod"])
            return redirect(f"{request.path}?success=backdrop_deleted")

        elif action == "backdrop_settings":
            mode = request.POST.get("backdrop_mode", "cover")
            if mode not in ("cover", "contain"):
                mode = "cover"
            try:
                opacity = max(0, min(100, int(request.POST.get("backdrop_opacity", 100))))
            except (ValueError, TypeError):
                opacity = 100
            css = _sanitize_css(request.POST.get("backdrop_css", ""))[:2000]
            css_mobile = _sanitize_css(request.POST.get("backdrop_css_mobile", ""))[:2000]
            feuser.backdrop_mode = mode
            feuser.backdrop_opacity = opacity
            feuser.backdrop_css = css
            feuser.backdrop_css_mobile = css_mobile
            feuser.last_mod = timezone.now()
            feuser.save(update_fields=["backdrop_mode", "backdrop_opacity", "backdrop_css", "backdrop_css_mobile", "last_mod"])
            return redirect(f"{request.path}?success=backdrop_settings")

        elif action == "profile":
            profile_form = ProfileForm(request.POST, instance=feuser)
            if profile_form.is_valid():
                feuser.last_mod = timezone.now()
                if feuser.is_demo:
                    feuser.currency = profile_form.cleaned_data["currency"]
                    feuser.month_start_day = profile_form.cleaned_data["month_start_day"]
                    feuser.month_start_prev = profile_form.cleaned_data["month_start_prev"]
                    feuser.unspent_allowance_action = profile_form.cleaned_data["unspent_allowance_action"]
                    feuser.save(update_fields=["currency", "month_start_day", "month_start_prev", "unspent_allowance_action", "last_mod"])
                else:
                    profile_form.save()
                return redirect(f"{request.path}?success=profile")

        elif action == "notifications":
            if feuser.is_demo:
                return redirect(f"{request.path}?success=notifications")
            notifications_form = NotificationPreferencesForm(request.POST, instance=feuser)
            if notifications_form.is_valid():
                feuser.last_mod = timezone.now()
                notifications_form.save()
                return redirect(f"{request.path}?success=notifications")

        elif action == "ai":
            if feuser.is_demo:
                return redirect(f"{request.path}?success=ai")
            ai_form = AISettingsForm(request.POST, instance=feuser)
            if ai_form.is_valid():
                feuser.last_mod = timezone.now()
                ai_form.save()
                return redirect(f"{request.path}?success=ai")

        elif action == "email":
            if feuser.is_demo:
                return redirect(f"{request.path}?success=email")
            email_form = ChangeEmailForm(request.POST, feuser=feuser)
            if email_form.is_valid():
                new_email = email_form.cleaned_data["email"]
                if settings.DISABLE_EMAILING:
                    feuser.email = new_email
                    feuser.last_mod = timezone.now()
                    feuser.save(update_fields=["email", "last_mod"])
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
            if feuser.is_demo:
                return redirect(f"{request.path}?success=password")
            password_form = ChangePasswordForm(request.POST, feuser=feuser)
            if password_form.is_valid():
                feuser.set_password(password_form.cleaned_data["new_password"])
                feuser.last_mod = timezone.now()
                feuser.save(update_fields=["password", "last_mod"])
                return redirect(f"{request.path}?success=password")

    return render(request, "feusers/profile.html", {
        "active_nav": "profile",
        "profile_form": profile_form,
        "notifications_form": notifications_form,
        "ai_form": ai_form,
        "email_form": email_form,
        "password_form": password_form,
        "success": success,
        "email_error": email_error,
        "picture_error": picture_error,
        "backdrop_error": backdrop_error,
    })


def account_export(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    from django.db.models import Q
    from budget.models import Category, Dashboard, DashboardCard, Expense, ExpenseDataOverlay, ScheduledExpense, Tag
    from buddies.models import BuddyLink, BuddySpending, DummyUser, Project, ProjectMember

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # ------------------------------------------------------------------
        # profile.csv — dynamic: all concrete fields except security tokens
        # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # Helper: write a queryset as CSV (all concrete fields minus skip,
        # plus optional extra=(header, fn) computed columns).
        # ------------------------------------------------------------------
        def _write_model_csv(p, qs, *, skip=(), extra=()):
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

        _TAG_IDS = ("tag_ids", lambda obj: ",".join(str(t.uid) for t in obj.tags.all()))

        # ------------------------------------------------------------------
        # categories.csv / tags.csv
        # ------------------------------------------------------------------
        p = io.StringIO()
        _write_model_csv(p, Category.objects.filter(owning_feuser=feuser), skip={"owning_feuser"})
        zf.writestr("categories.csv", p.getvalue())

        p = io.StringIO()
        _write_model_csv(p, Tag.objects.filter(owning_feuser=feuser), skip={"owning_feuser"})
        zf.writestr("tags.csv", p.getvalue())

        # ------------------------------------------------------------------
        # expenses.csv — own expenses (identical scheme used for foreign too).
        # category_id is kept as a raw FK; tag_ids are comma-separated UIDs.
        # ------------------------------------------------------------------
        _EXPENSE_SKIP = {"owning_feuser"}
        own_expenses_qs = (
            Expense.objects.filter(owning_feuser=feuser)
            .prefetch_related("tags")
            .order_by("date_created")
        )
        p = io.StringIO()
        _write_model_csv(p, own_expenses_qs, skip=_EXPENSE_SKIP, extra=[_TAG_IDS])
        zf.writestr("expenses.csv", p.getvalue())

        # ------------------------------------------------------------------
        # expense_participants.csv — BuddySpending rows for own expenses.
        # Lists who shared each of the feuser's expenses (feusers and offline
        # buddies), with their share and approval state.
        # ------------------------------------------------------------------
        own_spendings = (
            BuddySpending.objects
            .filter(expense__owning_feuser=feuser)
            .select_related("expense", "participant_feuser", "participant_dummy")
            .order_by("expense__date_created", "uid")
        )
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow([
            "expense_id", "expense_title",
            "participant_feuser_email", "participant_dummy_id", "participant_dummy_name",
            "share_percent", "approval_state", "consent_set_at",
        ])
        for bs in own_spendings:
            w.writerow([
                bs.expense_id,
                bs.expense.title,
                bs.participant_feuser.email if bs.participant_feuser_id else "",
                bs.participant_dummy_id or "",
                bs.participant_dummy.display_name if bs.participant_dummy_id else "",
                bs.share_percent,
                bs.approval_state,
                bs.consent_set_at.isoformat() if bs.consent_set_at else "",
            ])
        zf.writestr("expense_participants.csv", p.getvalue())

        # ------------------------------------------------------------------
        # scheduled_expenses.csv / dashboard_cards.csv
        # ------------------------------------------------------------------
        p = io.StringIO()
        _write_model_csv(
            p,
            ScheduledExpense.objects.filter(owning_feuser=feuser).prefetch_related("tags"),
            skip={"owning_feuser"},
            extra=[_TAG_IDS],
        )
        zf.writestr("scheduled_expenses.csv", p.getvalue())

        p = io.StringIO()
        _write_model_csv(
            p,
            Dashboard.objects.filter(owning_feuser=feuser),
            skip={"owning_feuser"},
        )
        zf.writestr("dashboards.csv", p.getvalue())

        p = io.StringIO()
        _write_model_csv(
            p,
            DashboardCard.objects.filter(owning_feuser=feuser),
            skip={"owning_feuser"},
        )
        zf.writestr("dashboard_cards.csv", p.getvalue())

        # ------------------------------------------------------------------
        # foreign_expenses.csv — expenses owned by other feusers where this
        # user is a participant. Identical column scheme to expenses.csv.
        # ------------------------------------------------------------------
        foreign_expense_ids = (
            BuddySpending.objects
            .filter(participant_feuser=feuser)
            .values_list("expense_id", flat=True)
        )
        foreign_expenses_qs = (
            Expense.objects
            .filter(uid__in=foreign_expense_ids)
            .select_related("category", "owning_feuser").prefetch_related("tags")
            .order_by("date_created")
        )
        p = io.StringIO()
        _write_model_csv(
            p, foreign_expenses_qs,
            skip=_EXPENSE_SKIP | {"category"},
            extra=[("owning_feuser_email", lambda obj: obj.owning_feuser.email)],
        )
        zf.writestr("foreign_expenses.csv", p.getvalue())

        # ------------------------------------------------------------------
        # expense_overlays.csv — feuser's personal category/tags/note on
        # shared expenses (own or foreign).
        # category_id and tag_ids use raw IDs, consistent with expenses.csv.
        # ------------------------------------------------------------------
        overlays = (
            ExpenseDataOverlay.objects
            .filter(feuser=feuser)
            .select_related("expense")
            .prefetch_related("tags")
        )
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["expense_id", "expense_title", "category_id", "tag_ids", "note", "last_mod"])
        for ov in overlays:
            w.writerow([
                ov.expense_id,
                ov.expense.title,
                ov.category_id or "",
                ",".join(str(t.uid) for t in ov.tags.all()),
                "" if ov.note is None else ov.note,
                ov.last_mod.isoformat(),
            ])
        zf.writestr("expense_overlays.csv", p.getvalue())

        # ------------------------------------------------------------------
        # real_user_buddies.csv — confirmed real-user buddy connections.
        # ------------------------------------------------------------------
        links = (
            BuddyLink.objects
            .filter(Q(user_a=feuser) | Q(user_b=feuser))
            .select_related("user_a", "user_b")
        )
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["buddy_email", "buddy_first_name", "buddy_last_name", "linked_since"])
        for lnk in links:
            other = lnk.other(feuser)
            w.writerow([other.email, other.first_name, other.last_name, lnk.created_at.isoformat()])
        zf.writestr("real_user_buddies.csv", p.getvalue())

        # ------------------------------------------------------------------
        # project_memberships.csv — all projects feuser is a member of.
        # ------------------------------------------------------------------
        memberships = (
            ProjectMember.objects
            .filter(feuser=feuser)
            .select_related("group")
            .order_by("joined_at")
        )
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["project_id", "project_name", "is_admin", "joined_at"])
        for m in memberships:
            w.writerow([
                m.group_id,
                m.group.name,
                m.group.admin_feuser_id == feuser.pk,
                m.joined_at.isoformat(),
            ])
        zf.writestr("project_memberships.csv", p.getvalue())

        # ------------------------------------------------------------------
        # administered_projects.csv — full project records for projects where
        # feuser is admin.
        # project_offline_members.csv — offline members of those projects.
        # Media: projects/{uid}/picture.webp and offline member pics.
        # ------------------------------------------------------------------
        admin_projects = list(
            Project.objects.filter(admin_feuser=feuser).order_by("name")
        )
        p = io.StringIO()
        _write_model_csv(
            p,
            Project.objects.filter(admin_feuser=feuser).order_by("name"),
            skip={"admin_feuser"},
        )
        zf.writestr("administered_projects.csv", p.getvalue())

        project_offline_members = (
            DummyUser.objects
            .filter(owning_group__admin_feuser=feuser)
            .select_related("owning_group")
            .order_by("owning_group__name", "display_name")
        )
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["uid", "project_id", "project_name", "display_name", "is_archive", "has_picture", "created_at", "last_mod"])
        for d in project_offline_members:
            w.writerow([
                d.pk,
                d.owning_group_id,
                d.owning_group.name,
                d.display_name,
                d.is_archive,
                d.profile_picture,
                d.created_at.isoformat(),
                d.last_mod.isoformat(),
            ])
        zf.writestr("project_offline_members.csv", p.getvalue())

        for proj in admin_projects:
            if proj.group_picture:
                pic = settings.MEDIA_ROOT / "bgpics" / f"{proj.pk}.webp"
                if pic.exists():
                    zf.write(pic, f"projects/{proj.pk}/picture.webp")

        for d in project_offline_members:
            if d.profile_picture:
                pic = settings.MEDIA_ROOT / "offline-buddy-ppic" / f"{d.pk}.jpg"
                if pic.exists():
                    zf.write(pic, f"projects/{d.owning_group_id}/offline_members/{d.pk}.jpg")

        # ------------------------------------------------------------------
        # offline_buddies.csv — offline (dummy) buddies owned personally by
        # feuser (owning_feuser=feuser, regardless of project membership).
        # Includes profile pictures.
        # ------------------------------------------------------------------
        personal_dummies = (
            DummyUser.objects
            .filter(owning_feuser=feuser)
            .order_by("display_name")
        )
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["uid", "display_name", "is_archive", "has_picture", "created_at", "last_mod"])
        for d in personal_dummies:
            w.writerow([d.pk, d.display_name, d.is_archive, d.profile_picture, d.created_at.isoformat(), d.last_mod.isoformat()])
        zf.writestr("offline_buddies.csv", p.getvalue())

        for d in personal_dummies:
            if d.profile_picture:
                pic = settings.MEDIA_ROOT / "offline-buddy-ppic" / f"{d.pk}.jpg"
                if pic.exists():
                    zf.write(pic, f"offline_buddies/{d.pk}.jpg")

        # ------------------------------------------------------------------
        # Feuser media files.
        # ------------------------------------------------------------------
        if feuser.profile_picture:
            ppic = settings.MEDIA_ROOT / "ppics" / f"{feuser.pk}.jpg"
            if ppic.exists():
                zf.write(ppic, "profile_picture.jpg")

        if feuser.custom_backdrop:
            backdrop = settings.MEDIA_ROOT / "backdrops" / f"{feuser.pk}.png"
            if backdrop.exists():
                zf.write(backdrop, "custom_backdrop.png")

    _name_parts = f"{feuser.first_name} {feuser.last_name}".strip()
    _name_slug = re.sub(r"[^A-Za-z0-9]+", "_", _name_parts).strip("_")
    _name_part = f"_{_name_slug}" if _name_slug else ""
    filename = f"comaney_export{_name_part}_{timezone.localdate().isoformat()}.zip"
    response = HttpResponse(buf.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def account_delete(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    if feuser.is_demo:
        return render(request, "feusers/account_delete.html", {"error": "Demo accounts cannot be deleted."})

    error = None
    if request.method == "POST":
        password = request.POST.get("password", "")
        if not feuser.check_password(password):
            error = "Incorrect password."
        else:
            from buddies.services import BuddyLifecycleService
            BuddyLifecycleService.handle_account_deletion(feuser)
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
    if user.is_demo:
        return redirect("profile")
    user.generate_api_key()
    user.last_mod = timezone.now()
    user.save(update_fields=["api_key", "last_mod"])
    return redirect("profile")


def api_key_revoke(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    user = _get_session_feuser(request)
    if not user:
        return redirect("login")
    user.revoke_api_key()
    user.last_mod = timezone.now()
    user.save(update_fields=["api_key", "last_mod"])
    return redirect("profile")


