"""
Unit tests for feusers/yubico_otp_service.py: the Yubico OTP validation
protocol (request signing, response signature verification, public id
extraction). The HTTP transport is injected (`fetch`), so the full
verify_otp() round trip is testable here with a fake transport standing in
for the real validation server - no network, Django, or DB required.

Run with:
    venv/bin/pytest tests/unit/test_yubico_otp_service.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from urllib.parse import parse_qs, urlparse

from feusers.yubico_otp_service import _sign, public_id_from_otp, verify_otp

CLIENT_ID = "12345"
SECRET_KEY = "MTIzNDU2Nzg5MDEyMzQ1Ng=="  # base64 of an arbitrary 16-byte key
PUBLIC_ID = "cccccccccccc"
VALID_OTP = PUBLIC_ID + "b" * 32  # 12-char public id + 32-char payload, all modhex


class TestPublicIdFromOtp:

    def test_extracts_the_first_twelve_characters(self):
        assert public_id_from_otp(VALID_OTP) == PUBLIC_ID

    def test_strips_whitespace_and_lowercases(self):
        assert public_id_from_otp(f"  {VALID_OTP.upper()}  ") == PUBLIC_ID

    def test_rejects_wrong_length(self):
        assert public_id_from_otp(VALID_OTP[:-1]) is None
        assert public_id_from_otp(VALID_OTP + "b") is None

    def test_rejects_non_modhex_characters(self):
        # 'a' is not in the modhex alphabet (cbdefghijklnrtuv).
        assert public_id_from_otp("a" * 44) is None

    def test_rejects_empty_string(self):
        assert public_id_from_otp("") is None


def _fake_server_response(request_params: dict, *, status="OK") -> str:
    """Builds a signed response the way a real Yubico-protocol validation
    server would, echoing back the request's otp/nonce. Reuses _sign() -
    the same routine production code uses to both sign and verify - so this
    fake is internally consistent with itself, matching how the project
    tests other self-contained protocol/crypto helpers."""
    fields = {
        "otp": request_params["otp"][0],
        "nonce": request_params["nonce"][0],
        "status": status,
    }
    fields["h"] = _sign(fields, SECRET_KEY)
    return "\r\n".join(f"{k}={v}" for k, v in fields.items())


def _fetch_from(handler):
    """Wraps a (params: dict) -> str handler into the `fetch(url) -> str`
    shape verify_otp() expects, parsing the query string for the handler."""
    def fetch(url):
        params = parse_qs(urlparse(url).query)
        return handler(params)
    return fetch


class TestVerifyOtp:

    def test_accepts_a_matching_ok_response(self):
        fetch = _fetch_from(_fake_server_response)
        assert verify_otp(VALID_OTP, client_id=CLIENT_ID, secret_key=SECRET_KEY, server="https://example.test", fetch=fetch) == PUBLIC_ID

    def test_malformed_otp_is_rejected_without_a_network_call(self):
        def fetch(url):
            raise AssertionError("fetch must not be called for a malformed OTP")
        assert verify_otp("not-an-otp", client_id=CLIENT_ID, secret_key=SECRET_KEY, server="https://example.test", fetch=fetch) is None

    def test_network_error_is_treated_as_verification_failure(self):
        def fetch(url):
            raise OSError("connection refused")
        assert verify_otp(VALID_OTP, client_id=CLIENT_ID, secret_key=SECRET_KEY, server="https://example.test", fetch=fetch) is None

    def test_rejects_replayed_otp_status(self):
        fetch = _fetch_from(lambda params: _fake_server_response(params, status="REPLAYED_OTP"))
        assert verify_otp(VALID_OTP, client_id=CLIENT_ID, secret_key=SECRET_KEY, server="https://example.test", fetch=fetch) is None

    def test_rejects_bad_otp_status(self):
        fetch = _fetch_from(lambda params: _fake_server_response(params, status="BAD_OTP"))
        assert verify_otp(VALID_OTP, client_id=CLIENT_ID, secret_key=SECRET_KEY, server="https://example.test", fetch=fetch) is None

    def test_rejects_a_response_signed_with_the_wrong_key(self):
        def fetch(url):
            params = parse_qs(urlparse(url).query)
            fields = {"otp": params["otp"][0], "nonce": params["nonce"][0], "status": "OK"}
            fields["h"] = _sign(fields, "d3JvbmdrZXl3cm9uZ2tleXdyb25na2V5")
            return "\r\n".join(f"{k}={v}" for k, v in fields.items())
        assert verify_otp(VALID_OTP, client_id=CLIENT_ID, secret_key=SECRET_KEY, server="https://example.test", fetch=fetch) is None

    def test_rejects_a_response_missing_its_signature(self):
        def fetch(url):
            params = parse_qs(urlparse(url).query)
            return f"otp={params['otp'][0]}\r\nnonce={params['nonce'][0]}\r\nstatus=OK"
        assert verify_otp(VALID_OTP, client_id=CLIENT_ID, secret_key=SECRET_KEY, server="https://example.test", fetch=fetch) is None

    def test_rejects_a_response_for_a_different_otp(self):
        """A response echoing back a different otp than what was sent must
        not be accepted, even if correctly signed - it isn't a response to
        this request (e.g. a stale/cached or cross-wired reply)."""
        other_otp = "d" * 12 + "e" * 32
        def fetch(url):
            params = parse_qs(urlparse(url).query)
            fields = {"otp": other_otp, "nonce": params["nonce"][0], "status": "OK"}
            fields["h"] = _sign(fields, SECRET_KEY)
            return "\r\n".join(f"{k}={v}" for k, v in fields.items())
        assert verify_otp(VALID_OTP, client_id=CLIENT_ID, secret_key=SECRET_KEY, server="https://example.test", fetch=fetch) is None

    def test_strips_trailing_slash_from_server_url(self):
        seen = {}
        def fetch(url):
            seen["url"] = url
            params = parse_qs(urlparse(url).query)
            return _fake_server_response(params)
        verify_otp(VALID_OTP, client_id=CLIENT_ID, secret_key=SECRET_KEY, server="https://example.test/", fetch=fetch)
        assert seen["url"].startswith("https://example.test/wsapi/2.0/verify?")
        assert "//wsapi" not in seen["url"]
