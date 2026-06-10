"""YubiKey OTP second-factor setup. Login verification reuses
_LOGIN_VERIFIERS in feusers/views/twofa.py like every other method; this
module only builds a new YubikeyFactor from a freshly touched OTP."""
from django.conf import settings
from django.shortcuts import redirect, render

from ..models import YubikeyFactor
from ..second_factor_registry import get_all_factors
from ..second_factor_service import finish_setup, register_factor
from ..utils import _get_session_feuser
from ..yubico_otp_service import verify_otp


def yubikey_setup(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")
    if feuser.is_demo:
        return redirect("profile")
    if not (settings.YUBICO_CLIENT_ID and settings.YUBICO_SECRET_KEY):
        return redirect("profile")

    error = None
    is_first_factor = not get_all_factors(feuser)

    if request.method == "POST":
        otp = request.POST.get("otp", "").strip()
        public_id = verify_otp(
            otp, client_id=settings.YUBICO_CLIENT_ID, secret_key=settings.YUBICO_SECRET_KEY,
            server=settings.YUBICO_SERVER,
        )
        if public_id is None:
            error = "We couldn't verify that YubiKey. Please touch it again."
        elif YubikeyFactor.objects.filter(public_id=public_id).exists():
            error = "This YubiKey is already registered."
        else:
            label = request.POST.get("label", "").strip() or "YubiKey"
            factor = YubikeyFactor(feuser=feuser, label=label, public_id=public_id)
            make_primary = request.POST.get("make_primary") == "1"
            first = register_factor(factor, make_primary=make_primary)
            return finish_setup(request, feuser, first)

    return render(request, "feusers/yubikey_setup.html", {
        "error": error,
        "is_first_factor": is_first_factor,
    })


def verify_yubikey_login(request, factor) -> bool:
    """Shape matches every other method's login verifier: (request, factor)
    -> bool. Registered in feusers/views/twofa.py's dispatch table under the
    "yubikey" key."""
    otp = request.POST.get("otp", "").strip()
    public_id = verify_otp(
        otp, client_id=settings.YUBICO_CLIENT_ID, secret_key=settings.YUBICO_SECRET_KEY,
        server=settings.YUBICO_SERVER,
    )
    return public_id is not None and public_id == factor.public_id
