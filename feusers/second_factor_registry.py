"""Registry of second-factor authentication methods.

TOTP and FIDO2/WebAuthn are the two current methods; both are specializations
of the same shape (see feusers.models.second_factor.SecondFactorAuth). Adding
a further method later (e.g. a dedicated YubiKey-specific flow) means adding
a model next to TOTPFactor/WebAuthnFactor and calling register_factor_type()
once. Login, removal, and profile views drive entirely off this registry and
must never branch on a method name directly, so a new method needs no changes
anywhere else.

This module has no Django dependency on purpose: it is pure bookkeeping over
plain Python objects, which keeps it unit-testable without a database.
"""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FactorType:
    key: str                    # "totp" | "webauthn" | ...
    model: type                 # the concrete Django model for this method
    display_name: str           # "Authenticator App" | "Security Key"
    setup_url_name: str         # URL name for the "add this method" flow
    challenge_template: str     # template partial rendered inside twofa_verify.html
    icon: str                   # static-relative path, e.g. "images/icons/key.png"


_REGISTRY: dict[str, FactorType] = {}


def register_factor_type(factor_type: FactorType) -> None:
    _REGISTRY[factor_type.key] = factor_type


def factor_type_for(key: str) -> FactorType:
    return _REGISTRY[key]


def all_factor_types() -> list[FactorType]:
    return list(_REGISTRY.values())


def method_key_of(factor: Any) -> str:
    for factor_type in _REGISTRY.values():
        if isinstance(factor, factor_type.model):
            return factor_type.key
    raise ValueError(f"Unregistered factor type: {type(factor)!r}")


def get_all_factors(feuser) -> list:
    """Single combined, time-ordered read across every registered factor
    table. Callers must fetch this once per request and reuse the result for
    both rendering and validating a POST: a factor added or removed by
    another session mid-request must never desync the two."""
    factors: list = []
    for factor_type in _REGISTRY.values():
        factors.extend(factor_type.model.objects.filter(feuser=feuser))
    return sorted(factors, key=lambda f: f.created_at)


def pick_primary_factor(factors: list):
    """Pure selection logic shared by get_primary_factor() and the login/
    removal views: prefer the flagged primary, else fall back to the first
    (oldest) factor. Takes an already-fetched list so callers that must
    reuse one DB snapshot per request (see get_all_factors) can call this
    without triggering another query."""
    for factor in factors:
        if factor.is_primary:
            return factor
    return factors[0] if factors else None


def get_primary_factor(feuser):
    return pick_primary_factor(get_all_factors(feuser))
