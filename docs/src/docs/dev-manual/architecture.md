# Architecture

## Django apps

Comaney is split into three Django apps and a project package.

### `comaney/` (project package)

Settings, root URL configuration, and middleware. Also contains a dynamic markdown renderer that serves optional public pages (imprint, privacy policy, etc.) from environment-variable-supplied markdown content.

### `feusers/`

Everything related to users and authentication. This app defines the `FeUser` model, which is Comaney's custom user type. It does **not** use `django.contrib.auth.User`.

Responsibilities: registration, login, logout, email confirmation, password reset, TOTP two-factor auth, API key management, account settings, and account deletion.

Session authentication works by storing `feuser_id` in the Django session after a successful login. The `@feuser_required` decorator (in `budget/decorators.py`) checks this on each request and sets `request.feuser`.

### `budget/`

The core budgeting functionality. Contains all models (`Expense`, `ScheduledExpense`, `Category`, `Tag`, `DashboardCard`), all budgeting views, and the business logic for:

- Expense CRUD and bulk actions
- Scheduled expense template management and cron-driven generation
- Category and tag management
- The modular dashboard (YAML card parsing and data computation)
- AI express creation
- Email notifications
- End-of-month rollover logic
- The query language parser (translates the search bar mini-language into Django Q objects)

### `api/`

A thin REST API layer over the `budget` models. Authenticated via Bearer token rather than session cookies. Contains serializers for converting model instances to JSON, and an `@_require_auth` decorator that validates the token and injects the `FeUser` into the view.

No business logic lives here that isn't already in the `budget` layer.

## URL routing

```
/                 → feusers app (login, register, public pages)
/budget/          → budget app (expenses, dashboard, scheduled, categories)
/api/v1/          → api app (Bearer token REST API)
/admin/           → Django admin
/docs/            → Docs site served from docs/build/site/
```

## Middleware

Requests pass through the middleware stack in this order:

1. **SystemMisconfiguredMiddleware**: injects a warning banner if the app is misconfigured (e.g., SMTP not set up).
2. **SecurityMiddleware**: Django's standard security headers.
3. **WhiteNoiseMiddleware**: serves compressed static files directly from Gunicorn.
4. **SessionMiddleware**: cookie-based session support.
5. **LastSeenMiddleware**: updates `feuser.last_seen` at most once every 5 minutes for authenticated requests.
6. Standard Django middleware (CSRF, messages, X-Frame-Options, etc.).

## Financial periods

All budget data is scoped to a financial period. The period is determined by the user's `month_start_day` and `month_start_prev` settings. `budget/date_utils.py` provides `financial_month_range()` and `financial_year_range()` to compute the date boundaries for any given month or year.

The dashboard, expense list, and API all accept `?year=` and `?month=` parameters and use these helpers to scope queries.

## Dashboard card system

Cards are stored as `DashboardCard` model instances containing only a raw YAML string and a creation timestamp. All layout and configuration information lives inside the YAML.

When the dashboard loads, the frontend fetches all cards via the session-authenticated card API. For each card, the server parses the YAML, applies the card's query filter against the current period, and computes either a scalar value (cell cards) or grouped chart data (bar/pie charts). The result is returned as JSON.

Cell cards with `method: custom` execute a user-supplied Python snippet in a sandboxed thread with a 2-second timeout and restricted builtins.

## Static files

SCSS and JS source files in `build/` are compiled to `static/dist/` by the build script. WhiteNoise serves them with a content-hash in the URL (via `CompressedManifestStaticFilesStorage`), enabling aggressive browser caching.

## Authentication flows

**Session auth (web UI):** On login, the server looks up the `FeUser` by email, verifies the submitted password with `check_password()`, and only then stores the user's database PK in the session as `feuser_id`. If TOTP is enabled, a `totp_pending_id` is stored instead and the user is redirected to a TOTP verification screen; the full session (`feuser_id`) is only established after the code is validated.

**Bearer token auth (REST API):** The `Authorization: Bearer <key>` header is read on every API request. The key is looked up against `FeUser.api_key` in the database.

**Registration protection:** The registration form uses a client-side proof-of-work challenge to deter bot signups. The browser must compute a hash nonce before the form can be submitted.
