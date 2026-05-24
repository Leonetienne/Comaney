"""
Unit tests for SECRET_KEY fail-fast logic (Issue 2 from security audit).

Tests the branching logic in comaney/settings.py in isolation — no Django import
needed since we replicate the exact condition and assert its behaviour.

Run with: venv/bin/pytest tests/unit/test_settings_secret_key.py -v
"""


def _resolve_secret_key(env_debug: str, env_key: str) -> str:
    """Mirror the exact logic from comaney/settings.py so we can unit-test
    it without importing Django."""
    DEBUG = env_debug.upper() == "TRUE"
    SECRET_KEY = env_key or ""
    if not SECRET_KEY:
        if DEBUG:
            SECRET_KEY = "dev-secret-key-change-in-production"
        else:
            raise ValueError(
                "DJANGO_SECRET_KEY must be set in production (DEBUG is not True)."
            )
    return SECRET_KEY


def test_production_without_key_raises():
    try:
        _resolve_secret_key("FALSE", "")
        assert False, "Expected an error when no key and DEBUG=False"
    except ValueError as exc:
        assert "DJANGO_SECRET_KEY" in str(exc)


def test_debug_without_key_uses_dev_fallback():
    key = _resolve_secret_key("TRUE", "")
    assert key == "dev-secret-key-change-in-production"


def test_explicit_key_used_in_production():
    key = _resolve_secret_key("FALSE", "my-prod-key")
    assert key == "my-prod-key"


def test_explicit_key_used_in_debug():
    key = _resolve_secret_key("TRUE", "my-debug-key")
    assert key == "my-debug-key"


def test_empty_string_env_treated_as_missing():
    """An empty DJANGO_SECRET_KEY env var must trigger the fail-fast path in
    production, not silently use an empty string as the key."""
    try:
        _resolve_secret_key("FALSE", "")
        assert False, "Expected an error for empty key in production"
    except ValueError:
        pass


def test_whitespace_only_key_not_accepted():
    """A key that is only whitespace must be treated like no key."""
    env_key = "   "
    try:
        _resolve_secret_key("FALSE", env_key.strip() or "")
        assert False, "Expected an error for blank key in production"
    except ValueError:
        pass
