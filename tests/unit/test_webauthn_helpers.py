"""
Unit tests for feusers/webauthn_helpers.py (RP ID derivation, FIDO2 sign-count
clone detection). Both helpers are dependency-free by design so this needs no
Django/DB. Run with:
    venv/bin/pytest tests/unit/test_webauthn_helpers.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from feusers.webauthn_helpers import rp_id_from_site_url, sign_count_is_valid


class TestRpIdFromSiteUrl:

    def test_extracts_hostname(self):
        assert rp_id_from_site_url("https://comaney.example.com") == "comaney.example.com"

    def test_strips_port(self):
        assert rp_id_from_site_url("http://localhost:8080") == "localhost"

    def test_strips_scheme_and_path(self):
        assert rp_id_from_site_url("https://example.com/some/path") == "example.com"

    def test_bare_ipv4_is_rejected(self):
        # WebAuthn does not accept an IP address as an RP ID.
        assert rp_id_from_site_url("http://192.168.1.5:8080") is None

    def test_bare_ipv6_is_rejected(self):
        assert rp_id_from_site_url("http://[::1]:8080") is None

    def test_empty_url_returns_none(self):
        assert rp_id_from_site_url("") is None


class TestSignCountIsValid:

    def test_strictly_increasing_counter_is_valid(self):
        assert sign_count_is_valid(5, 6) is True

    def test_equal_nonzero_counter_is_rejected(self):
        # A counter that didn't move at all (and isn't the "unsupported"
        # always-zero case) suggests a cloned authenticator replaying state.
        assert sign_count_is_valid(5, 5) is False

    def test_decreasing_counter_is_rejected(self):
        assert sign_count_is_valid(10, 3) is False

    def test_both_zero_is_treated_as_unsupported_not_a_clone(self):
        # Some legitimate resident-key authenticators never increment past 0.
        assert sign_count_is_valid(0, 0) is True

    def test_zero_to_nonzero_is_valid(self):
        assert sign_count_is_valid(0, 1) is True

    def test_nonzero_to_zero_is_rejected(self):
        # A counter that goes backward to zero is a strong clone signal, not
        # "unsupported" (that only applies when both sides are 0).
        assert sign_count_is_valid(5, 0) is False
