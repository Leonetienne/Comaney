"""FIDO2/WebAuthn second factor: registration (setup) and login-assertion
verification. The login challenge page (feusers/views/twofa.py) dispatches
into verify_login_assertion()/build_login_options() for the "webauthn" method
key; it never touches py_webauthn directly.
"""
import json
import time

from django.conf import settings
from django.shortcuts import redirect, render
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from comaney.json_utils import safe_json

from ..models import WebAuthnFactor
from ..second_factor_registry import get_all_factors
from ..second_factor_service import generate_recovery_code, register_factor
from ..utils import _get_session_feuser
from ..webauthn_helpers import rp_id_from_site_url, sign_count_is_valid

_CHALLENGE_MAX_AGE = 120  # seconds; a stale/replayed ceremony must be rejected


def _rp_id():
    return rp_id_from_site_url(settings.SITE_URL)


def _origin() -> str:
    return settings.SITE_URL.rstrip("/")


def _store_challenge(request, session_key: str, challenge: bytes) -> None:
    request.session[session_key] = {"value": bytes_to_base64url(challenge), "ts": time.time()}


def _pop_challenge(request, session_key: str) -> bytes | None:
    """Single-use: removed on read regardless of outcome, so a failed or
    successful attempt can never be replayed against the same challenge."""
    data = request.session.pop(session_key, None)
    if not data:
        return None
    if time.time() - data.get("ts", 0) > _CHALLENGE_MAX_AGE:
        return None
    return base64url_to_bytes(data["value"])


def _transports_from(credential_json: str) -> str:
    try:
        raw = json.loads(credential_json)
        transports = raw.get("response", {}).get("transports") or []
    except (ValueError, TypeError, AttributeError):
        transports = []
    return ",".join(transports)


def webauthn_setup(request):
    feuser = _get_session_feuser(request)
    if not feuser:
        return redirect("login")
    if feuser.is_demo:
        return redirect("profile")

    rp_id = _rp_id()
    if not rp_id:
        return redirect("profile")

    error = None
    if request.method == "POST":
        credential_json = request.POST.get("credential_json", "")
        challenge = _pop_challenge(request, "webauthn_setup_challenge")
        label = request.POST.get("label", "").strip() or "Security Key"
        make_primary = request.POST.get("make_primary") == "1"

        if not challenge or not credential_json:
            error = "Your registration session expired. Please try again."
        else:
            try:
                verification = verify_registration_response(
                    credential=credential_json,
                    expected_challenge=challenge,
                    expected_rp_id=rp_id,
                    expected_origin=_origin(),
                )
            except (WebAuthnException, ValueError):
                error = "We couldn't register that security key. Please try again."
            else:
                factor = WebAuthnFactor(
                    feuser=feuser,
                    label=label,
                    credential_id=bytes_to_base64url(verification.credential_id),
                    public_key=bytes_to_base64url(verification.credential_public_key),
                    sign_count=verification.sign_count,
                    transports=_transports_from(credential_json),
                )
                is_first = register_factor(factor, make_primary=make_primary)
                recovery_code = generate_recovery_code(feuser) if is_first else None
                return render(request, "feusers/webauthn_setup.html", {
                    "done": True,
                    "recovery_code": recovery_code,
                })

    existing = [f for f in get_all_factors(feuser) if isinstance(f, WebAuthnFactor)]
    is_first_factor = not get_all_factors(feuser)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="Comaney",
        user_id=str(feuser.pk).encode(),
        user_name=feuser.email,
        user_display_name=(f"{feuser.first_name} {feuser.last_name}".strip() or feuser.email),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(f.credential_id)) for f in existing
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    _store_challenge(request, "webauthn_setup_challenge", options.challenge)
    return render(request, "feusers/webauthn_setup.html", {
        # safe_json (not the raw py_webauthn JSON string): first/last name
        # are user-editable and end up in this payload as user.displayName,
        # so this is a real </script>-breakout surface, not paranoia.
        "options_json": safe_json(json.loads(options_to_json(options))),
        "is_first_factor": is_first_factor,
        "error": error,
    })


def build_login_options(request, factor: WebAuthnFactor) -> str:
    """Returns a safe_json string ready to embed in a <script> block via
    |safe (see comaney/json_utils.py)."""
    options = generate_authentication_options(
        rp_id=_rp_id(),
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(factor.credential_id))],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    _store_challenge(request, "twofa_webauthn_challenge", options.challenge)
    return safe_json(json.loads(options_to_json(options)))


def verify_login_assertion(request, factor: WebAuthnFactor) -> bool:
    """Shape matches every other method's login verifier: (request, factor) -> bool.
    Registered in feusers/views/twofa.py's dispatch table under the "webauthn" key."""
    credential_json = request.POST.get("credential_json", "")
    challenge = _pop_challenge(request, "twofa_webauthn_challenge")
    if not challenge or not credential_json:
        return False
    try:
        verification = verify_authentication_response(
            credential=credential_json,
            expected_challenge=challenge,
            expected_rp_id=_rp_id(),
            expected_origin=_origin(),
            credential_public_key=base64url_to_bytes(factor.public_key),
            credential_current_sign_count=factor.sign_count,
        )
    except (WebAuthnException, ValueError):
        return False
    if not sign_count_is_valid(factor.sign_count, verification.new_sign_count):
        return False
    factor.sign_count = verification.new_sign_count
    factor.save(update_fields=["sign_count"])
    return True
