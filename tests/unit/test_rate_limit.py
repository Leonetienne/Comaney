"""
Unit tests for the shared-cache rate limiter (feusers/rate_limit.py).

The limiter now stores attempt timestamps in Django's cache framework so state
is shared across Gunicorn workers. These tests point it at an in-process locmem
cache (a stand-in for the shared DB cache used in production) and assert the
sliding-window / _MAX_ATTEMPTS semantics are unchanged.

No DB required. Run with: venv/bin/pytest tests/unit/test_rate_limit.py -v
"""
import time

import pytest

# The limiter now stores state in Django's cache framework. The lightweight unit
# venv may not have Django installed (the e2e stack exercises the real DB cache);
# skip cleanly there rather than erroring at collection.
django = pytest.importorskip("django")
from django.conf import settings  # noqa: E402

if not settings.configured:
    settings.configure(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    )
    django.setup()

from django.core.cache import cache  # noqa: E402

import feusers.rate_limit as rl  # noqa: E402


def setup_function():
    cache.clear()


def test_not_limited_initially():
    assert not rl.is_limited("login", "1.2.3.4")


def test_limited_after_max_failures():
    for _ in range(5):
        rl.record_failure("login", "1.2.3.4")
    assert rl.is_limited("login", "1.2.3.4")


def test_four_failures_not_enough():
    for _ in range(4):
        rl.record_failure("login", "1.2.3.4")
    assert not rl.is_limited("login", "1.2.3.4")


def test_clear_resets_limit():
    for _ in range(5):
        rl.record_failure("login", "1.2.3.4")
    rl.clear("login", "1.2.3.4")
    assert not rl.is_limited("login", "1.2.3.4")


def test_different_kinds_are_independent():
    for _ in range(5):
        rl.record_failure("login", "1.2.3.4")
    assert not rl.is_limited("totp", "1.2.3.4")


def test_different_identifiers_are_independent():
    for _ in range(5):
        rl.record_failure("login", "1.2.3.4")
    assert not rl.is_limited("login", "5.6.7.8")


def test_per_account_key_traps_across_ips():
    # Failures recorded against one account bucket accumulate regardless of the
    # IP bucket: this is the per-account throttle the ticket adds.
    for _ in range(5):
        rl.record_failure("login-account", "victim@example.com")
    assert rl.is_limited("login-account", "victim@example.com")
    assert not rl.is_limited("login-account", "someone-else@example.com")


def test_shared_store_not_doubled_across_workers():
    # Two "workers" sharing the same cache backend must see one combined counter,
    # not one each. Interleave failures and assert the combined count trips at 5.
    for _ in range(3):
        rl.record_failure("login", "1.2.3.4")   # "worker A"
    for _ in range(2):
        rl.record_failure("login", "1.2.3.4")   # "worker B"
    assert rl.is_limited("login", "1.2.3.4")


def test_old_failures_expire():
    now = time.time()
    cache.set(rl._cache_key("login", "1.2.3.4"), [now - 61] * 5)
    assert not rl.is_limited("login", "1.2.3.4")


def test_only_recent_failures_count():
    now = time.time()
    # 3 expired + 4 recent = 4 active (< 5, not limited)
    cache.set(rl._cache_key("login", "1.2.3.4"), [now - 61] * 3 + [now - 1] * 4)
    assert not rl.is_limited("login", "1.2.3.4")


def test_five_recent_failures_trigger_limit():
    now = time.time()
    cache.set(rl._cache_key("login", "1.2.3.4"), [now - 1] * 5)
    assert rl.is_limited("login", "1.2.3.4")


def test_clear_nonexistent_key_is_safe():
    rl.clear("login", "9.9.9.9")  # must not raise
