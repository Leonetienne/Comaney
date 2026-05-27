"""
Regression tests for TICKET-06 — missing secure-cookie / host hardening settings.

For a finance app several standard Django security settings are absent and
ALLOWED_HOSTS defaults to a wildcard. These tests import the real settings module
inside the container under a production-like environment (DEBUG=FALSE) and assert
the hardening is in place:

  - SESSION_COOKIE_SECURE is True in production
  - CSRF_COOKIE_SECURE is True in production
  - ALLOWED_HOSTS does not silently default to ["*"] when unset in production

The settings module is imported directly (not via manage.py); os.environ is
adjusted *before* import so the test controls DEBUG / secret key / ALLOWED_HOSTS
regardless of the container's own environment.

EXPECTED TO FAIL until the settings are added: today the cookie-secure flags are
absent and the ALLOWED_HOSTS default is "*".

Run with (live stack container comaney-web-1 required):
    pytest tests/e2e/test_security_settings_hardening.py -sxv | tee logfile.log
"""
import subprocess

from helpers import DOCKER_WEB

MISSING = "MISSING"


def _settings_report(debug: str, drop_allowed_hosts: bool) -> dict:
    """Import comaney.settings inside the container under a controlled env and
    return a dict of the security-relevant values (as strings)."""
    lines = [
        "import os",
        f"os.environ['DEBUG'] = {debug!r}",
        "os.environ['DJANGO_SECRET_KEY'] = 'test-only-secret-key'",
    ]
    if drop_allowed_hosts:
        lines.append("os.environ.pop('ALLOWED_HOSTS', None)")
    lines += [
        "import comaney.settings as s",
        f"print('SESSION_COOKIE_SECURE', getattr(s, 'SESSION_COOKIE_SECURE', {MISSING!r}))",
        f"print('CSRF_COOKIE_SECURE', getattr(s, 'CSRF_COOKIE_SECURE', {MISSING!r}))",
        "print('ALLOWED_HOSTS', repr(s.ALLOWED_HOSTS))",
    ]
    script = "\n".join(lines)
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"settings import failed:\n{result.stderr}"
    report = {}
    for ln in result.stdout.splitlines():
        key, _, val = ln.partition(" ")
        report[key] = val.strip()
    return report


class TestProductionCookieHardening:

    def test_session_cookie_secure_in_production(self):
        report = _settings_report(debug="FALSE", drop_allowed_hosts=False)
        assert report["SESSION_COOKIE_SECURE"] == "True", \
            f"SESSION_COOKIE_SECURE not enabled in production (got {report['SESSION_COOKIE_SECURE']})"

    def test_csrf_cookie_secure_in_production(self):
        report = _settings_report(debug="FALSE", drop_allowed_hosts=False)
        assert report["CSRF_COOKIE_SECURE"] == "True", \
            f"CSRF_COOKIE_SECURE not enabled in production (got {report['CSRF_COOKIE_SECURE']})"


class TestAllowedHostsDefault:

    def test_no_wildcard_default_in_production(self):
        report = _settings_report(debug="FALSE", drop_allowed_hosts=True)
        assert report["ALLOWED_HOSTS"] != "['*']", \
            "ALLOWED_HOSTS silently defaults to wildcard ['*'] in production"


class TestDevStaysPermissive:
    """The transport hardening must be gated on production so local http dev
    keeps working. This should pass both before and after the fix."""

    def test_dev_import_succeeds_and_not_forced_secure(self):
        report = _settings_report(debug="TRUE", drop_allowed_hosts=False)
        assert report["SESSION_COOKIE_SECURE"] != "True", \
            "SESSION_COOKIE_SECURE must not be forced in DEBUG/dev mode"
