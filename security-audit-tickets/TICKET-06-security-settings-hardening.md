# TICKET-06 — Missing secure-cookie / host / transport hardening settings

**Severity:** Medium (session cookie theft over plaintext, Host-header abuse)
**Type:** Deployment / configuration hardening
**Components:** `comaney/settings.py`

## Summary

For a finance application, several standard Django security settings are absent, and
`ALLOWED_HOSTS` defaults to a wildcard. None of the following are set:
`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`,
`SECURE_HSTS_SECONDS`, `SECURE_PROXY_SSL_HEADER`. Confirmed absent:

```
$ grep -n "SESSION_COOKIE\|CSRF_COOKIE\|SECURE_\|SAMESITE" comaney/settings.py
(no matches)
```

Consequences:

- **Session cookie not marked `Secure`.** The auth session (`feuser_id`) can be sent
  over plaintext HTTP, exposing it to network attackers if any request hits `http://`.
- **CSRF cookie not marked `Secure`.**
- **No HTTPS redirect / HSTS**, so downgrade to HTTP is possible.
- **`ALLOWED_HOSTS` defaults to `"*"`** (`comaney/settings.py:17`) when the env var is
  unset, disabling Host-header validation. This weakens defenses against Host-header
  poisoning — relevant here because password-reset and email-confirmation links are
  built from `SITE_URL` (mostly fixed), but Host validation is still a baseline
  control that should not be off by default.

Django's defaults do already give `SESSION_COOKIE_HTTPONLY=True` and
`SESSION_COOKIE_SAMESITE="Lax"`, so those two are fine; the gaps above are the ones to
close.

## Proposed fix

Add production-guarded security settings to `comaney/settings.py`. Gate the
transport-security ones on "not DEBUG" so local HTTP dev keeps working:

```python
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "TRUE").upper() == "TRUE"
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Only if terminating TLS at a trusted proxy that sets this header:
    if os.environ.get("TRUST_PROXY_SSL_HEADER", "").upper() == "TRUE":
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

And tighten the `ALLOWED_HOSTS` default so a wildcard is opt-in rather than the
fallback:

```python
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["*"] if DEBUG else []   # empty => must be configured in prod
```

Document the new env vars (`SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`,
`TRUST_PROXY_SSL_HEADER`) alongside the existing table in `CLAUDE.md` / deployment
docs. Coordinate `SECURE_SSL_REDIRECT` / `SECURE_PROXY_SSL_HEADER` with the actual
reverse-proxy setup to avoid redirect loops.

## Regression testing

- **Settings smoke test**: import settings with `DEBUG=False` and a set
  `ALLOWED_HOSTS`, assert `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` are `True`;
  with `DEBUG=True`, assert dev still permissive.
- **`manage.py check --deploy`**: run in CI against a prod-like env; assert the
  previously-raised warnings for these settings are gone.
- **Host validation**: a request with an unexpected `Host` header returns 400 when
  `ALLOWED_HOSTS` is configured (not `*`).
- **Manual**: confirm the app still serves and logs in over the real TLS-terminating
  proxy without a redirect loop.
