"""TOTP ("Authenticator App") second-factor setup. Login verification,
removal, and recovery are handled generically in feusers/views/twofa.py; this
module only builds and confirms a new TOTPFactor."""
from django.shortcuts import redirect, render

from ..models import TOTPFactor
from ..second_factor_registry import get_all_factors
from ..second_factor_service import generate_recovery_code, register_factor
from ..utils import _get_session_feuser


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
    if feuser.is_demo:
        return redirect("profile")

    import pyotp
    error = None
    is_first_factor = not get_all_factors(feuser)

    if request.method == "POST":
        code   = request.POST.get("code", "").strip()
        secret = request.session.get("totp_setup_secret", "")
        if not secret:
            return redirect("totp_setup")
        totp = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            label = request.POST.get("label", "").strip() or "Authenticator App"
            factor = TOTPFactor(feuser=feuser, secret=secret, label=label)
            make_primary = request.POST.get("make_primary") == "1"
            first = register_factor(factor, make_primary=make_primary)
            del request.session["totp_setup_secret"]
            recovery_code = generate_recovery_code(feuser) if first else None
            return render(request, "feusers/totp_setup.html", {
                "recovery_code": recovery_code,
                "done": True,
            })
        error = "Invalid code: please try again."
    else:
        secret = pyotp.random_base32()
        request.session["totp_setup_secret"] = secret

    secret = request.session["totp_setup_secret"]
    uri    = pyotp.totp.TOTP(secret).provisioning_uri(feuser.email, issuer_name="Comaney")
    return render(request, "feusers/totp_setup.html", {
        "qr_b64": _totp_qr_b64(uri),
        "secret": secret,
        "error": error,
        "is_first_factor": is_first_factor,
    })
