"""Email second-factor setup and the single "send code" ajax endpoint.

Login verification reuses _LOGIN_VERIFIERS in feusers/views/twofa.py like
every other method; this module only builds a new EmailFactor and sends the
code. A feuser may only ever have one EmailFactor (unlike TOTP/WebAuthn,
every instance would target the exact same address), which is what lets
email_factor_send_code resolve its target from session state alone, with no
client-supplied method_key/factor_id: an authenticated feuser has at most one
persisted EmailFactor (or, mid-setup, one candidate secret in their own
session), and a pending login has at most one active factor per session.
"""
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..email_factor_service import TOO_MANY_MSG, TOO_SOON_MSG, generate_secret, request_send, verify_code
from ..models import EmailFactor, FeUser
from ..second_factor_registry import get_all_factors
from ..second_factor_service import finish_setup, register_factor
from ..utils import _get_session_feuser


def email_factor_setup(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")
    if feuser.is_demo:
        return redirect("profile")
    if settings.DISABLE_EMAILING:
        return redirect("profile")
    if EmailFactor.objects.filter(feuser=feuser).exists():
        return redirect("profile")

    error = None
    is_first_factor = not get_all_factors(feuser)

    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        secret = request.session.get("email_factor_setup_secret", "")
        if not secret:
            return redirect("email_factor_setup")
        if verify_code(secret, code):
            factor = EmailFactor(feuser=feuser, secret=secret, label="Email Code")
            make_primary = request.POST.get("make_primary") == "1"
            first = register_factor(factor, make_primary=make_primary)
            del request.session["email_factor_setup_secret"]
            return finish_setup(request, feuser, first)
        error = "Invalid code: please try again."
    elif not request.session.get("email_factor_setup_secret"):
        # Only generate a fresh secret if this is a genuinely new setup
        # session: unlike TOTP (where the QR is simply redrawn from whatever
        # secret is current), a code may already be sitting in the feuser's
        # inbox by the time a reload hits this branch, and regenerating here
        # would silently invalidate it.
        request.session["email_factor_setup_secret"] = generate_secret()

    return render(request, "feusers/email_factor_setup.html", {
        "error": error,
        "is_first_factor": is_first_factor,
        "feuser_email": feuser.email,
    })


def email_factor_send_code(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    feuser = _get_session_feuser(request)
    if feuser is not None:
        existing = EmailFactor.objects.filter(feuser=feuser).first()
        if existing is not None:
            # An already-authenticated feuser acting on their own factor
            # (factor_test, or a removal/recovery-regen confirm step) - not
            # an in-progress login, so it must not share the "login" bucket:
            # testing the method must never block signing in.
            secret = existing.secret
            purpose = "confirm"
        else:
            secret = request.session.get("email_factor_setup_secret", "")
            if not secret:
                return JsonResponse({"error": "Nothing to send."}, status=400)
            purpose = "setup"
        target_pk, target_email = feuser.pk, feuser.email
    else:
        pending_id = request.session.get("twofa_pending_id")
        if not pending_id or request.session.get("twofa_active_method") != "email":
            return JsonResponse({"error": "Not available."}, status=400)
        try:
            user = FeUser.objects.get(pk=pending_id, is_active=True)
        except FeUser.DoesNotExist:
            return JsonResponse({"error": "Not available."}, status=400)
        factor = EmailFactor.objects.filter(
            feuser=user, pk=request.session.get("twofa_active_factor_id"),
        ).first()
        if factor is None:
            return JsonResponse({"error": "Not available."}, status=400)
        secret = factor.secret
        purpose = "login"
        target_pk, target_email = user.pk, user.email

    sent, error = request_send(target_pk, target_email, secret, purpose=purpose)
    if not sent:
        # "cooldown" is not really a failure: it means a code was already
        # sent within the last minute (e.g. moments ago during setup) and is
        # still valid, since the cooldown is far shorter than the code's
        # 5-minute lifetime. The frontend shows this reassuringly rather than
        # as an error. "hourly_cap" and anything else are genuine problems.
        if error == TOO_SOON_MSG:
            status, reason = 429, "cooldown"
        elif error == TOO_MANY_MSG:
            status, reason = 429, "hourly_cap"
        else:
            status, reason = 502, None
        return JsonResponse({"error": error, "reason": reason}, status=status)
    return JsonResponse({"sent": True})
