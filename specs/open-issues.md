# Open Issues

Gaps found while compiling this database (2026-10-13): places where the user or admin
manual, the code and the former spec files disagree, and questions those specs left
open. The requirements in `requirements/` describe what the code does. Each issue
needs a decision: fix the code, fix the docs, or accept it and delete the entry.

## Docs disagree with code

| # | Topic | Docs say | Code does | Requirement |
|---|---|---|---|---|
| 1 | Registration disabled | `admin-manual/registration.md`, `environment-variables.md`: registration page returns 403 | Returns 404 | `req~accounts.registration.availability~1` |
| 2 | Email settle link | `user-manual/notifications.md`: "Mark as settled" works without logging in | Requires a logged-in session of the owner | `req~notifications.reminder.links~1` |
| 3 | Missing email config | `admin-manual/email.md`: banner on every page, app keeps working | Every request answered with the misconfiguration page (500) | `req~operations.misconfigured~1` |
| 4 | Line chart buckets | `user-manual/dashboard/cards/line-chart.md`: days in month view, weeks in year view | The date range UI always yields daily buckets, so a year range plots 365 points | `req~dashboard.type.line-buckets~1` |
| 5 | Demo AI budget | `admin-manual/shared-ai-access.md`: a `DEMO_USER_AI_BUDGET` of 0 means no shared AI for the demo | 0 or unset falls back to the global limit (as `environment-variables.md` says) | `req~ai.access.special-budget~1` |
| 6 | Demo reset trigger | AGENTS.md: reset once the last demo user has been inactive a week | Resets as soon as any demo user was last seen over a week ago, even if another was active | `req~demo.reset~1` |
| 7 | Data export period | `user-manual/data-export.md`: "a specific month, or a full year in year view" | Month/year view no longer exists; the date range picker applies | `req~export.list-csv~1` |
| 8 | Testing guide | `dev-manual/testing.md`: `tests_new/`, `pytest -vsx`, "no unit tests" | Tests live in `tests/{unit,e2e,integration}`, run with `-v` only, unit tests exist | `req~constraints.test-conventions~1` |
| 9 | 2FA wording | `dev-manual/architecture.md`, `admin-manual/console-commands.md`, `registration.md`: TOTP and security keys only | Four methods incl. email code and YubiKey OTP | `req~twofa.methods~1` |
| 10 | Bulk actions | `user-manual/expenses.md`: Settle, Unsettle, Delete | Also add tag, remove tag, set category | `req~expenses.list.bulk~1` |
| 11 | API dashboard | `user-manual/api-access.md` does not list it | `GET /api/v1/dashboard/` exists | `req~api.dashboard~1` |
| 12 | Account export contents | `user-manual/data-export.md` lists 5 kinds of data | Export also holds overlays, partnership, pending invites and approvals, buddy data, second factors, Sankey graph | `req~export.account~1` |

## Behaviour that looks unintended

### 13. No password strength policy
`AUTH_PASSWORD_VALIDATORS` is configured, but no registration, reset or change form
calls `validate_password`, so any non-empty password is accepted.

### 14. Session key not rotated on login
The former `fido2-spec.md` asked for `request.session.cycle_key()` after a completed
login (session fixation hardening). Login and 2FA completion set `feuser_id` without
rotating the session key.

### 15. Partnership onboarding drops labels outside expenses
Applying the onboarding wizard rewrites tags and categories only on the invitee's own
expenses, then deletes and recreates the invitee's whole catalog. Recurring templates
and expense overlays reference the deleted rows, so they lose their category (set to
null) and tags. Unverified by test.

### 16. Cloned security key not flagged in the UI
The former `fido2-spec.md` asked to flag a credential with an inconsistent signature
counter in the account settings. The login is rejected, but no flag is shown.

## Questions the former specs left open

### 17. Sankey snapshot history
Each Generate is a throwaway render; whether past generations should be kept was never
decided.

### 18. Sankey keyboard accessibility
No keyboard alternative for wiring or moving nodes exists beyond the priority input.

### 19. WebAuthn discoverable credentials
Passwordless login with resident keys was ruled out of scope for now, not rejected.
