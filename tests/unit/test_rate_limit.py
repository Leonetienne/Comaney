"""
Unit tests for the in-memory rate limiter (feusers/rate_limit.py).

No Django/DB required. Run with: venv/bin/pytest tests/unit/test_rate_limit.py -v
"""

import time

import feusers.rate_limit as rl


def setup_function():
    rl._attempts.clear()


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


def test_old_failures_expire():
    key = ("login", "1.2.3.4")
    now = time.monotonic()
    rl._attempts[key] = [now - 61] * 5
    assert not rl.is_limited("login", "1.2.3.4")


def test_only_recent_failures_count():
    key = ("login", "1.2.3.4")
    now = time.monotonic()
    # 3 expired + 4 recent = 4 active (< 5, not limited)
    rl._attempts[key] = [now - 61] * 3 + [now - 1] * 4
    assert not rl.is_limited("login", "1.2.3.4")


def test_five_recent_failures_trigger_limit():
    key = ("login", "1.2.3.4")
    now = time.monotonic()
    rl._attempts[key] = [now - 1] * 5
    assert rl.is_limited("login", "1.2.3.4")


def test_clear_nonexistent_key_is_safe():
    rl.clear("login", "9.9.9.9")  # must not raise
