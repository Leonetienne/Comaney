"""Unified second-factor login challenge, method switching, global recovery
code, and factor management (remove / set primary / regenerate recovery).

Verification for a given method is dispatched through _LOGIN_VERIFIERS
rather than branching on the method name inline, so a future method only
needs one extra dict entry here plus its own setup view."""
import json

import pyotp
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..email_factor_service import clear_login_send_throttle, verify_code as _verify_email_code
from ..models import FeUser
from ..rate_limit import clear as rl_clear, is_limited, record_failure
from ..second_factor_registry import factor_type_for, get_all_factors, method_key_of, pick_primary_factor
from ..second_factor_service import (
    consume_recovery_code, generate_recovery_code,
    remove_factor as _remove_factor, set_primary as _set_primary,
)
from ..utils import _get_session_feuser, _record_login
from .webauthn import build_login_options, verify_login_assertion
from .yubikey import verify_yubikey_login

_SESSION_KEYS = (
    "twofa_pending_id", "twofa_active_method", "twofa_active_factor_id",
    "twofa_webauthn_challenge",
)


def _verify_totp_login(request, factor) -> bool:
    code = request.POST.get("code", "").strip()
    return pyotp.TOTP(factor.secret).verify(code, valid_window=1)


def _verify_email_login(request, factor) -> bool:
    code = request.POST.get("code", "").strip()
    if not _verify_email_code(factor.secret, code):
        return False
    # Reused for the real login challenge, factor_test, and
    # factor_remove/recovery_regenerate's confirm step alike: entering the
    # current code proves the account owner can read their inbox, so the
    # login-purpose send throttle no longer needs to hold them back
    # afterward (e.g. logging out and immediately signing back in).
    clear_login_send_throttle(factor.feuser_id)
    return True


_LOGIN_VERIFIERS = {
    "totp": _verify_totp_login,
    "webauthn": verify_login_assertion,
    "email": _verify_email_login,
    "yubikey": verify_yubikey_login,
}


def _clear_pending(request):
    for key in _SESSION_KEYS:
        request.session.pop(key, None)


def _find(factors, method_key, factor_id):
    return next(
        (f for f in factors if method_key_of(f) == method_key and f.pk == factor_id), None,
    )


def _pick_confirm_factor(request, candidates):
    """Which factor's challenge to show for a re-auth step (factor removal,
    recovery-code regeneration). Defaults to the first candidate; a "confirm
    with a different method" link can override via ?cm=<key>&cid=<id>."""
    key, fid = request.GET.get("cm"), request.GET.get("cid")
    if key and fid:
        match = next((f for f in candidates if method_key_of(f) == key and str(f.pk) == fid), None)
        if match is not None:
            return match
    return candidates[0]


def twofa_verify(request):
    pending_id = request.session.get("twofa_pending_id")
    if not pending_id:
        return redirect("login")
    try:
        user = FeUser.objects.get(pk=pending_id, is_active=True)
    except FeUser.DoesNotExist:
        _clear_pending(request)
        return redirect("login")

    factors = get_all_factors(user)
    if not factors:
        # Every factor was removed elsewhere (e.g. recovery code used from
        # another tab) while this login was pending. Fail closed rather than
        # error or loop.
        _clear_pending(request)
        return redirect("login")

    active_key = request.session.get("twofa_active_method")
    active_id = request.session.get("twofa_active_factor_id")
    active = _find(factors, active_key, active_id)
    if active is None:
        active = pick_primary_factor(factors)
        request.session["twofa_active_method"] = method_key_of(active)
        request.session["twofa_active_factor_id"] = active.pk
        active_key = method_key_of(active)

    rl_key = str(pending_id)
    error = None

    if request.method == "POST":
        if is_limited("twofa", rl_key):
            error = "Too many failed attempts. Please wait a moment and try again."
        else:
            # Re-check the active factor still exists at submit time: it may
            # have been removed from another tab between render and submit.
            current = _find(get_all_factors(user), active_key, active.pk)
            if current is None:
                error = "This method is no longer available. Please choose another."
                factors = get_all_factors(user)
                if not factors:
                    _clear_pending(request)
                    return redirect("login")
                active = pick_primary_factor(factors)
                active_key = method_key_of(active)
                request.session["twofa_active_method"] = active_key
                request.session["twofa_active_factor_id"] = active.pk
            else:
                verify_fn = _LOGIN_VERIFIERS[active_key]
                if verify_fn(request, current):
                    rl_clear("twofa", rl_key)
                    _record_login(user)
                    _clear_pending(request)
                    request.session["feuser_id"] = user.pk
                    return redirect("landing_page")
                record_failure("twofa", rl_key)
                error = ("Invalid code: please try again." if active_key in ("totp", "email")
                          else "Verification failed. Please try again.")

    factors = get_all_factors(user)  # fresh snapshot for rendering the picker
    active = _find(factors, active_key, active.pk) or pick_primary_factor(factors)
    other_factors = [f for f in factors if f.pk != active.pk or method_key_of(f) != active_key]
    factor_type = factor_type_for(active_key)

    context = {
        "error": error,
        "active_factor": active,
        "active_method": active_key,
        "active_display_name": factor_type.display_name,
        "challenge_template": factor_type.challenge_template,
        "other_factors": [(method_key_of(f), f) for f in other_factors],
    }
    if active_key == "webauthn":
        context["webauthn_options_json"] = build_login_options(request, active)

    return render(request, "feusers/twofa_verify.html", context)


def twofa_verify_switch(request, method_key, factor_id):
    pending_id = request.session.get("twofa_pending_id")
    if not pending_id:
        return redirect("login")
    try:
        user = FeUser.objects.get(pk=pending_id, is_active=True)
    except FeUser.DoesNotExist:
        _clear_pending(request)
        return redirect("login")

    target = _find(get_all_factors(user), method_key, factor_id)
    if target is not None:
        request.session["twofa_active_method"] = method_key
        request.session["twofa_active_factor_id"] = target.pk
        request.session.pop("twofa_webauthn_challenge", None)
    return redirect("twofa_verify")


def twofa_verify_recovery(request):
    pending_id = request.session.get("twofa_pending_id")
    if not pending_id:
        return redirect("login")

    rl_key = str(pending_id)
    error = None
    if request.method == "POST":
        if is_limited("twofa", rl_key):
            error = "Too many failed attempts. Please wait a moment and try again."
        else:
            try:
                user = FeUser.objects.get(pk=pending_id, is_active=True)
            except FeUser.DoesNotExist:
                return redirect("login")
            if consume_recovery_code(user, request.POST.get("recovery", "")):
                rl_clear("twofa", rl_key)
                _record_login(user)
                _clear_pending(request)
                request.session["feuser_id"] = user.pk
                return redirect("landing_page")
            record_failure("twofa", rl_key)
            error = "Invalid recovery code."

    return render(request, "feusers/twofa_verify.html", {"error": error, "recovery_mode": True})


def factor_remove(request, method_key, factor_id):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")

    factors = get_all_factors(feuser)
    target = _find(factors, method_key, factor_id)
    if target is None:
        return redirect("profile")

    others = [f for f in factors if f is not target]

    if not others:
        # The user's only factor: nothing else to re-authenticate with. This
        # is equivalent to disabling 2FA entirely, and remains reachable via
        # the global recovery code if even this is out of reach. Still gated
        # behind an explicit POST: a bare GET (link prefetch, accidental
        # click) must never mutate state.
        if request.method == "POST":
            _remove_factor(target)
            return redirect("profile")
        factor_type = factor_type_for(method_key)
        return render(request, "feusers/factor_remove_solo.html", {
            "target_method": method_key,
            "target_id": target.pk,
            "target_display_name": factor_type.display_name,
            "target_label": target.label,
        })

    rl_key = f"{feuser.pk}:remove"
    error = None
    recovery_mode = request.GET.get("recovery") == "1" or request.POST.get("recovery_mode") == "1"

    if request.method == "POST":
        if is_limited("twofa", rl_key):
            error = "Too many failed attempts. Please wait a moment and try again."
        elif recovery_mode:
            if consume_recovery_code(feuser, request.POST.get("recovery", "")):
                rl_clear("twofa", rl_key)
                return redirect("profile")
            record_failure("twofa", rl_key)
            error = "Invalid recovery code."
        else:
            confirm_key = request.POST.get("confirm_method")
            confirm_id = request.POST.get("confirm_factor_id", "")
            confirm_factor = next(
                (f for f in others if method_key_of(f) == confirm_key and str(f.pk) == confirm_id), None,
            )
            if confirm_factor is None:
                error = "Please choose a method to confirm with."
            else:
                verify_fn = _LOGIN_VERIFIERS[confirm_key]
                if verify_fn(request, confirm_factor):
                    rl_clear("twofa", rl_key)
                    # The target may have been removed by another tab already.
                    still_there = _find(get_all_factors(feuser), method_key, factor_id)
                    if still_there is not None:
                        _remove_factor(still_there)
                    return redirect("profile")
                record_failure("twofa", rl_key)
                error = "Verification failed."

    factor_type = factor_type_for(method_key)
    confirm_factor = _pick_confirm_factor(request, others)
    confirm_key = method_key_of(confirm_factor)
    confirm_factor_type = factor_type_for(confirm_key)
    context = {
        "error": error,
        "recovery_mode": recovery_mode,
        "target_method": method_key,
        "target_id": target.pk,
        "target_display_name": factor_type.display_name,
        "target_label": target.label,
        "other_factors": [(method_key_of(f), f) for f in others],
        "confirm_method": confirm_key,
        "confirm_factor": confirm_factor,
        "challenge_template": confirm_factor_type.challenge_template,
    }
    if confirm_key == "webauthn" and not recovery_mode:
        context["webauthn_options_json"] = build_login_options(request, confirm_factor)
    return render(request, "feusers/factor_remove.html", context)


def factor_set_primary(request, method_key, factor_id):
    feuser = _get_session_feuser(request)
    if not feuser or request.method != "POST":
        return redirect("profile")
    target = _find(get_all_factors(feuser), method_key, factor_id)
    if target is not None:
        _set_primary(feuser, target)
    return redirect("profile")


def factor_rename(request, method_key, factor_id):
    feuser = _get_session_feuser(request)
    if not feuser:
        return JsonResponse({"error": "Not authenticated."}, status=401)
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    target = _find(get_all_factors(feuser), method_key, factor_id)
    if target is None:
        return JsonResponse({"error": "Not found."}, status=404)

    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        data = {}
    label = data.get("label", "").strip()
    if not label:
        return JsonResponse({"error": "Name required."}, status=400)
    if len(label) > 64:
        return JsonResponse({"error": "Name must be 64 characters or fewer."}, status=400)

    target.label = label
    target.save(update_fields=["label"])
    return JsonResponse({"label": target.label})


def factor_test(request, method_key, factor_id):
    """Lets a user try a specific factor in isolation (e.g. tap one of
    several same-named security keys) without touching login/session state.
    Verification is dispatched through the same _LOGIN_VERIFIERS table and
    the registry's challenge_template as the real login challenge, so a
    future method needs no extra code here."""
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")
    target = _find(get_all_factors(feuser), method_key, factor_id)
    if target is None:
        return redirect("profile")

    result = None
    if request.method == "POST":
        result = _LOGIN_VERIFIERS[method_key](request, target)

    factor_type = factor_type_for(method_key)
    context = {
        "target_method": method_key,
        "target_id": target.pk,
        "target_display_name": factor_type.display_name,
        "target_label": target.label,
        "challenge_template": factor_type.challenge_template,
        "result": result,
    }
    if method_key == "webauthn":
        context["webauthn_options_json"] = build_login_options(request, target)
    return render(request, "feusers/factor_test.html", context)


def recovery_regenerate(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")
    if feuser.is_demo:
        return redirect("profile")

    factors = get_all_factors(feuser)
    if not factors:
        return redirect("profile")

    rl_key = f"{feuser.pk}:recovery-regen"
    error = None
    new_code = None

    if request.method == "POST":
        if is_limited("twofa", rl_key):
            error = "Too many failed attempts. Please wait a moment and try again."
        else:
            confirm_key = request.POST.get("confirm_method")
            confirm_id = request.POST.get("confirm_factor_id", "")
            confirm_factor = next(
                (f for f in factors if method_key_of(f) == confirm_key and str(f.pk) == confirm_id), None,
            )
            if confirm_factor is None:
                error = "Please choose a method to confirm with."
            else:
                verify_fn = _LOGIN_VERIFIERS[confirm_key]
                if verify_fn(request, confirm_factor):
                    rl_clear("twofa", rl_key)
                    new_code = generate_recovery_code(feuser)
                else:
                    record_failure("twofa", rl_key)
                    error = "Verification failed."

    confirm_factor = _pick_confirm_factor(request, factors)
    confirm_key = method_key_of(confirm_factor)
    confirm_factor_type = factor_type_for(confirm_key)
    context = {
        "error": error,
        "new_code": new_code,
        "other_factors": [(method_key_of(f), f) for f in factors],
        "confirm_method": confirm_key,
        "confirm_factor": confirm_factor,
        "challenge_template": confirm_factor_type.challenge_template,
    }
    if confirm_key == "webauthn" and not new_code:
        context["webauthn_options_json"] = build_login_options(request, confirm_factor)
    return render(request, "feusers/recovery_regenerate.html", context)
