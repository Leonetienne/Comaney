"""
Unit tests for feusers/second_factor_registry.py.

The registry is deliberately dependency-free (no Django import at all), so
these tests use plain stand-in classes instead of the real TOTPFactor/
WebAuthnFactor models. That keeps them fast and DB-free, matching this
project's convention that TOTP/2FA behavior needing a database is covered by
e2e tests instead (see tests/e2e/auth/).

No Django/DB required. Run with:
    venv/bin/pytest tests/unit/test_second_factor_registry.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest

from feusers.second_factor_registry import (
    FactorType, register_factor_type, factor_type_for, all_factor_types,
    method_key_of, pick_primary_factor,
)


class _FakeTOTP:
    def __init__(self, created_at, is_primary=False):
        self.created_at = created_at
        self.is_primary = is_primary


class _FakeWebAuthn:
    def __init__(self, created_at, is_primary=False):
        self.created_at = created_at
        self.is_primary = is_primary


@pytest.fixture(autouse=True)
def clean_registry():
    """Each test registers its own fake types in an isolated copy of the
    module-level registry dict, so tests can't see each other's types."""
    import feusers.second_factor_registry as reg
    original = dict(reg._REGISTRY)
    reg._REGISTRY.clear()
    yield
    reg._REGISTRY.clear()
    reg._REGISTRY.update(original)


def _register_fakes():
    register_factor_type(FactorType(
        key="totp", model=_FakeTOTP, display_name="Authenticator App",
        setup_url_name="totp_setup", challenge_template="feusers/twofa_challenge_totp.html",
        icon="images/icons/qr-code.png",
    ))
    register_factor_type(FactorType(
        key="webauthn", model=_FakeWebAuthn, display_name="Security Key",
        setup_url_name="webauthn_setup", challenge_template="feusers/twofa_challenge_webauthn.html",
        icon="images/icons/key.png",
    ))


def test_factor_type_for_returns_registered_type():
    _register_fakes()
    ft = factor_type_for("totp")
    assert ft.display_name == "Authenticator App"
    assert ft.model is _FakeTOTP


def test_all_factor_types_lists_every_registration():
    _register_fakes()
    keys = {ft.key for ft in all_factor_types()}
    assert keys == {"totp", "webauthn"}


def test_a_new_method_appears_without_touching_existing_ones():
    _register_fakes()

    class _FakeYubikey:
        def __init__(self, created_at, is_primary=False):
            self.created_at = created_at
            self.is_primary = is_primary

    register_factor_type(FactorType(
        key="yubikey", model=_FakeYubikey, display_name="YubiKey",
        setup_url_name="yubikey_setup", challenge_template="feusers/twofa_challenge_yubikey.html",
        icon="images/icons/yubikey.png",
    ))
    assert {ft.key for ft in all_factor_types()} == {"totp", "webauthn", "yubikey"}
    # Existing registrations are untouched by adding a new one.
    assert factor_type_for("totp").display_name == "Authenticator App"


def test_method_key_of_dispatches_by_instance_type():
    _register_fakes()
    assert method_key_of(_FakeTOTP(created_at=1)) == "totp"
    assert method_key_of(_FakeWebAuthn(created_at=1)) == "webauthn"


def test_method_key_of_raises_for_unregistered_type():
    _register_fakes()
    with pytest.raises(ValueError):
        method_key_of(object())


def test_pick_primary_factor_prefers_the_flagged_one():
    factors = [_FakeTOTP(created_at=1), _FakeWebAuthn(created_at=2, is_primary=True)]
    assert pick_primary_factor(factors) is factors[1]


def test_pick_primary_factor_falls_back_to_first_when_none_flagged():
    factors = [_FakeTOTP(created_at=1), _FakeWebAuthn(created_at=2)]
    assert pick_primary_factor(factors) is factors[0]


def test_pick_primary_factor_returns_none_for_empty_list():
    assert pick_primary_factor([]) is None
