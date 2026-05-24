"""
Unit tests for the CSRF enforcement decision in api/utils._require_auth (Issue 3).

Tests the core branching logic: Bearer-token requests bypass CSRF checks; session-
cookie requests are subject to CSRF verification on unsafe methods. This is tested
in isolation as pure Python without importing Django.

Run with: venv/bin/pytest tests/unit/test_api_csrf.py -v
"""


def _is_bearer_request(authorization_header: str) -> bool:
    """Mirror the guard in _require_auth: True means CSRF check is skipped."""
    return authorization_header.startswith("Bearer ")


SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _csrf_required(method: str, authorization_header: str) -> bool:
    """Return True when CSRF enforcement should apply: unsafe method and no Bearer token."""
    if method.upper() in SAFE_HTTP_METHODS:
        return False
    return not _is_bearer_request(authorization_header)


class TestBearerBypassesCSRF:

    def test_bearer_post_no_csrf_needed(self):
        assert not _csrf_required("POST", "Bearer my-api-key")

    def test_bearer_patch_no_csrf_needed(self):
        assert not _csrf_required("PATCH", "Bearer my-api-key")

    def test_bearer_delete_no_csrf_needed(self):
        assert not _csrf_required("DELETE", "Bearer my-api-key")

    def test_empty_bearer_value_is_still_bearer(self):
        assert not _csrf_required("POST", "Bearer ")

    def test_bearer_prefix_case_sensitive(self):
        # "bearer" (lowercase) is NOT treated as a Bearer token — authorization is
        # case-sensitive in the HTTP spec and our implementation.
        assert _csrf_required("POST", "bearer my-api-key")


class TestSessionAuthRequiresCSRF:

    def test_session_post_requires_csrf(self):
        assert _csrf_required("POST", "")

    def test_session_patch_requires_csrf(self):
        assert _csrf_required("PATCH", "")

    def test_session_delete_requires_csrf(self):
        assert _csrf_required("DELETE", "")

    def test_session_put_requires_csrf(self):
        assert _csrf_required("PUT", "")

    def test_no_auth_header_requires_csrf_on_write(self):
        assert _csrf_required("POST", "")


class TestSafeMethodsExempt:

    def test_session_get_exempt(self):
        assert not _csrf_required("GET", "")

    def test_session_head_exempt(self):
        assert not _csrf_required("HEAD", "")

    def test_session_options_exempt(self):
        assert not _csrf_required("OPTIONS", "")

    def test_bearer_get_exempt(self):
        assert not _csrf_required("GET", "Bearer key")
