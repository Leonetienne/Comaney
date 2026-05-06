import hashlib
import secrets

from django.shortcuts import redirect, render
from django.utils import timezone

from ..models import FeUser
from ..utils import _get_session_feuser, _record_login


def _totp_qr_b64(uri: str) -> str:
    import base64
    import io
    import qrcode
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
    recovery_mode = request.GET.get("recovery") == "1" or request.POST.get("recovery_mode") == "1"
    error = None
    if request.method == "POST":
        if recovery_mode:
            recovery = request.POST.get("recovery", "").strip().upper().replace("-", "")
            digest   = hashlib.sha256(recovery.encode()).hexdigest()
            if feuser.totp_recovery_hash and secrets.compare_digest(digest, feuser.totp_recovery_hash):
                feuser.totp_secret        = ""
                feuser.totp_enabled       = False
                feuser.totp_recovery_hash = ""
                feuser.save(update_fields=["totp_secret", "totp_enabled", "totp_recovery_hash"])
                return redirect("profile")
            error = "Invalid recovery code."
        else:
            code = request.POST.get("code", "").strip()
            if pyotp.TOTP(feuser.totp_secret).verify(code, valid_window=1):
                feuser.totp_secret  = ""
                feuser.totp_enabled = False
                feuser.save(update_fields=["totp_secret", "totp_enabled"])
                return redirect("profile")
            error = "Invalid code."
    return render(request, "feusers/totp_verify.html", {
        "error": error,
        "disable_mode": True,
        "recovery_mode": recovery_mode,
    })


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
            _record_login(user)
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
            user.last_login         = timezone.now()
            user.save(update_fields=["totp_secret", "totp_enabled", "totp_recovery_hash", "last_login"])
            del request.session["totp_pending_id"]
            request.session["feuser_id"] = user.pk
            return redirect("landing_page")
        error = "Invalid recovery code."

    return render(request, "feusers/totp_verify.html", {"error": error, "recovery_mode": True})
