"""YubiKey OTP second factor: https://developers.yubico.com/OTP/OTP_Walk-Through.html

Unlike TOTP/email, there is no secret held locally to check a code against:
verifying an OTP means a signed round trip to a Yubico-protocol validation
server (Yubico's own by default, or a self-hosted-compatible one, see
YUBICO_SERVER). The HTTP transport is injected (`fetch`) so the protocol
itself - building the signed request, verifying the signed response,
extracting the public id - stays unit-testable without a network call; only
the default `_http_fetch` touches the network.

A YubiKey OTP is a 44-character modhex string: a 12-character public id
(identifies the physical key) followed by a 32-character encrypted, per-touch
payload that changes on every press. The public id is what a factor is
stored and matched against - like WebAuthnFactor.credential_id, it uniquely
identifies the physical device, and the validation server itself rejects a
replayed OTP (status=REPLAYED_OTP), so there is no local counter to track.
"""
import base64
import hashlib
import hmac
import secrets
from urllib.parse import urlencode
from urllib.request import urlopen

_MODHEX = "cbdefghijklnrtuv"
_PUBLIC_ID_LEN = 12
_OTP_LEN = 44


def public_id_from_otp(otp: str) -> str | None:
    """The first 12 characters of a well-formed OTP, or None if `otp` isn't a
    44-character modhex string at all - rejected locally, without spending a
    validation-server round trip on something that obviously isn't a real
    YubiKey OTP."""
    otp = otp.strip().lower()
    if len(otp) != _OTP_LEN or any(c not in _MODHEX for c in otp):
        return None
    return otp[:_PUBLIC_ID_LEN]


def _sign(params: dict, secret_key: str) -> str:
    """HMAC-SHA1 over '&'-joined, alphabetically-sorted key=value pairs, per
    the Yubico OTP validation protocol, base64-encoded. Used both to sign an
    outgoing request and to check an incoming response's signature."""
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    digest = hmac.new(base64.b64decode(secret_key), message.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _parse_response(body: str) -> dict:
    result = {}
    for line in body.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _http_fetch(url: str) -> str:
    with urlopen(url, timeout=10) as resp:
        return resp.read().decode()


def verify_otp(otp: str, *, client_id: str, secret_key: str, server: str, fetch=_http_fetch) -> str | None:
    """Validate `otp` against the configured validation server. Returns the
    verified public id on success, None on any failure - malformed OTP,
    network error, a tampered/missing response signature, a response for a
    different request (nonce/otp echoed back must match what was sent), or a
    non-OK status (BAD_OTP, REPLAYED_OTP, ...). Never raises: every caller
    treats "not verified" uniformly regardless of the reason.
    """
    public_id = public_id_from_otp(otp)
    if public_id is None:
        return None

    nonce = secrets.token_hex(20)  # 40 hex chars; protocol wants 16-40
    params = {"id": client_id, "otp": otp, "nonce": nonce}
    params["h"] = _sign(params, secret_key)

    try:
        body = fetch(f"{server.rstrip('/')}/wsapi/2.0/verify?{urlencode(params)}")
    except Exception:
        return None

    response = _parse_response(body)
    if response.get("otp") != otp or response.get("nonce") != nonce:
        return None  # not a response to this request

    signature = response.pop("h", None)
    if signature is None or not hmac.compare_digest(_sign(response, secret_key), signature):
        return None
    if response.get("status") != "OK":
        return None
    return public_id
