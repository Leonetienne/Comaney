"""Service layer for the multi-method second-factor system.

Keeps the primary-factor invariant (exactly one is_primary=True factor per
user, across every registered method) and the global-recovery-code rules in
one place, so views never manipulate factor rows directly.
"""
import hashlib
import secrets

from django.db import transaction

from .second_factor_registry import get_all_factors


@transaction.atomic
def set_primary(feuser, factor) -> None:
    """Make `factor` the sole is_primary=True factor for `feuser`."""
    for existing in get_all_factors(feuser):
        if existing.is_primary and (type(existing), existing.pk) != (type(factor), factor.pk):
            existing.is_primary = False
            existing.save(update_fields=["is_primary"])
    if not factor.is_primary:
        factor.is_primary = True
        factor.save(update_fields=["is_primary"])


@transaction.atomic
def register_factor(factor, *, make_primary: bool) -> bool:
    """Persist a freshly built (unsaved) `factor` and resolve is_primary.

    A user's very first factor is always primary - there is nothing else to
    be primary over, regardless of the setup checkbox. Otherwise the checkbox
    decides; checking it demotes the previous primary in the same transaction.

    Returns True if this was the user's first-ever factor, so the caller
    knows to generate and display a new global recovery code.
    """
    is_first = not get_all_factors(factor.feuser)
    factor.is_primary = is_first
    factor.save()
    if not is_first and make_primary:
        set_primary(factor.feuser, factor)
    return is_first


@transaction.atomic
def remove_factor(factor):
    """Delete `factor`. If it was primary and others remain, promote the
    most-recently-created remaining factor and return it (None otherwise).
    If it was the user's last factor, also clear the recovery code since
    there is nothing left for it to protect."""
    feuser = factor.feuser
    was_primary = factor.is_primary
    factor.delete()
    remaining = get_all_factors(feuser)
    if not remaining:
        feuser.twofa_recovery_hash = ""
        feuser.save(update_fields=["twofa_recovery_hash"])
        return None
    if was_primary:
        newest = remaining[-1]
        set_primary(feuser, newest)
        return newest
    return None


def generate_recovery_code(feuser) -> str:
    """Generate and store a fresh global recovery code, returning the raw
    (dashed, human-readable) code. Callers must display it exactly once; it
    cannot be retrieved again afterward."""
    raw = secrets.token_hex(5).upper()
    feuser.twofa_recovery_hash = hashlib.sha256(raw.encode()).hexdigest()
    feuser.save(update_fields=["twofa_recovery_hash"])
    return f"{raw[:5]}-{raw[5:]}"


def _normalize_recovery_code(raw: str) -> str:
    return raw.strip().upper().replace("-", "")


def recovery_code_matches(feuser, submitted: str) -> bool:
    if not feuser.twofa_recovery_hash:
        return False
    digest = hashlib.sha256(_normalize_recovery_code(submitted).encode()).hexdigest()
    return secrets.compare_digest(digest, feuser.twofa_recovery_hash)


@transaction.atomic
def consume_recovery_code(feuser, submitted: str) -> bool:
    """Verify `submitted` against the stored recovery code; on match, delete
    every second factor of every method (the user has just proven they can
    access none of them, so all are equally suspect) and clear the code."""
    if not recovery_code_matches(feuser, submitted):
        return False
    for factor in get_all_factors(feuser):
        factor.delete()
    feuser.twofa_recovery_hash = ""
    feuser.save(update_fields=["twofa_recovery_hash"])
    return True
