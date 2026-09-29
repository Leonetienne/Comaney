# TICKET-04 — Brute-force rate limiting is per-process in-memory and IP-only

**Severity:** Medium (weakened brute-force protection on login / TOTP)
**Type:** Authentication hardening
**Components:** `feusers/rate_limit.py`, `feusers/views/auth.py`, `feusers/views/totp.py`

## Summary

The login / TOTP rate limiter stores attempt timestamps in a module-level Python
dict guarded by a thread lock. Two consequences:

1. **Per-process, not shared.** With more than one Gunicorn worker
   (`GUNICORN_WORKERS` is configurable and production commonly runs several), each
   worker keeps its own counter. The effective attempt budget is
   `_MAX_ATTEMPTS × worker_count`, and it resets whenever a worker restarts. An
   attacker's requests are load-balanced across workers, multiplying the allowance.

2. **IP-only keying.** The login limiter keys on `request.META["REMOTE_ADDR"]`
   (`feusers/views/auth.py:220`). Behind a reverse proxy this is often the proxy's
   address, so either all users share one bucket (self-DoS) or, if `REMOTE_ADDR` is
   attacker-influenced, buckets are trivially rotated. There is no per-account
   throttle, so credential-stuffing across many accounts from rotating IPs is
   unbounded.

## Root cause

`feusers/rate_limit.py`:

```python
_attempts: dict[tuple[str, str], list[float]] = defaultdict(list)  # process-local
```

State lives only in the worker's memory; nothing is shared or persisted.

## Proposed fix

- Back the limiter with a shared store. The app already runs MariaDB; the simplest
  drop-in is Django's cache framework with a shared backend (database cache table, or
  Redis/Memcached if available). Replace the dict operations in `is_limited` /
  `record_failure` / `clear` with atomic cache increments keyed by
  `(kind, identifier, window_bucket)`.
- Add a **per-account** dimension alongside the per-IP one for login and TOTP (key on
  the submitted email / pending user id), so throttling holds regardless of source IP.
- If a trusted proxy is in front, derive the client IP from the proxy's forwarded
  header (configured allowlist) instead of raw `REMOTE_ADDR`; otherwise keep
  `REMOTE_ADDR` but document that per-account throttling is the real control.

Keep the existing `_WINDOW`/`_MAX_ATTEMPTS` semantics; only the storage and the key
change.

## Regression testing

- **Unit**: point the limiter at a shared cache (locmem is fine for the test) and
  assert `is_limited` flips to `True` after `_MAX_ATTEMPTS` failures and clears after
  the window / on `clear`.
- **Multi-worker semantics**: a test that simulates two "workers" sharing the same
  cache backend and confirms the combined attempt count is enforced (not doubled).
- **Per-account**: failures against the same email from different IPs should trip the
  account throttle.
- **Login/TOTP flows**: existing lockout messages still appear after N failures and a
  successful login still calls `clear`.
