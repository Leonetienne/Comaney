"""Small, dependency-free helpers for the WebAuthn (FIDO2) second factor.

Kept free of Django imports so they can be unit tested directly, matching
this project's convention that pure algorithm logic lives in tests/unit/
without a database.
"""
import ipaddress
from urllib.parse import urlparse


def rp_id_from_site_url(site_url: str) -> str | None:
    """Derive a WebAuthn Relying Party ID from SITE_URL.

    Returns None if SITE_URL has no usable hostname, or the hostname is a
    bare IP address (WebAuthn does not accept an IP address as an RP ID), so
    callers can hide the security-key feature entirely instead of failing
    confusingly at ceremony time.
    """
    hostname = urlparse(site_url).hostname
    if not hostname:
        return None
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return hostname
    return None


def sign_count_is_valid(stored_count: int, new_count: int) -> bool:
    """FIDO2 clone-detection check for a WebAuthn assertion's signature counter.

    Some legitimate resident-key authenticators always report a counter of 0
    and never increment it; that is "unsupported", not a mismatch. Any other
    non-increasing counter indicates the credential may have been cloned and
    must be rejected.
    """
    if stored_count == 0 and new_count == 0:
        return True
    return new_count > stored_count
