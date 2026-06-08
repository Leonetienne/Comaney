"""Brute-force rate limiter for login / TOTP.

State is kept in Django's cache framework so it is shared across all Gunicorn
workers (and survives a single worker restart) rather than living in a
process-local dict. Configure a shared backend (the DB cache backend is fine)
via ``CACHES`` in settings; with the per-process default backend the limiter
still works but only within one worker.

Semantics are unchanged from the original in-memory version: at most
``_MAX_ATTEMPTS`` failures are tolerated within a sliding ``_WINDOW`` (seconds).
Because the store is shared between processes we key on wall-clock time
(``time.time()``) rather than ``time.monotonic()``, whose zero point differs
per process.

``window``/``max_attempts`` can be overridden per call for callers with
different thresholds (e.g. email 2FA send throttling); omit them to get the
original login/TOTP brute-force semantics.
"""
import time

from django.core.cache import cache

_WINDOW = 60
_MAX_ATTEMPTS = 5


def _cache_key(kind: str, identifier: str) -> str:
    return f"rl:{kind}:{identifier}"


def _recent(kind: str, identifier: str, now: float, window: int) -> list[float]:
    """Timestamps for this key that fall inside the current window."""
    timestamps = cache.get(_cache_key(kind, identifier)) or []
    return [t for t in timestamps if now - t < window]


def is_limited(kind: str, identifier: str, *, window: int = _WINDOW, max_attempts: int = _MAX_ATTEMPTS) -> bool:
    return len(_recent(kind, identifier, time.time(), window)) >= max_attempts


def record_failure(kind: str, identifier: str, *, window: int = _WINDOW) -> None:
    now = time.time()
    recent = _recent(kind, identifier, now, window)
    recent.append(now)
    cache.set(_cache_key(kind, identifier), recent, timeout=window)


def clear(kind: str, identifier: str) -> None:
    cache.delete(_cache_key(kind, identifier))
