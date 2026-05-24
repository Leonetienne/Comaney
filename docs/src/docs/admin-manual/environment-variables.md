# Environment Variables

All Comaney configuration is done via environment variables. This page documents every variable, its default, and its full behaviour.

---

## Core Django

### `DJANGO_SECRET_KEY`

**Default:** a hardcoded development placeholder (insecure)

The Django secret key is used to sign sessions, CSRF tokens, and other cryptographic primitives. In production, this **must** be set to a long random string.

**Generate one:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Keep this value secret. Rotating the secret key invalidates all existing sessions (everyone is logged out) and CSRF tokens.

---

### `DEBUG`

**Default:** `FALSE`

Set to `TRUE` to enable Django debug mode. In debug mode:

- Detailed error pages with full tracebacks are shown in the browser instead of the generic error page.
- Static files are served by Django directly (no WhiteNoise compression).
- Additional Django developer tooling is activated.

**Never run with `DEBUG=TRUE` in production.** Debug pages can expose sensitive configuration.

---

### `ALLOWED_HOSTS`

**Default:** `*` (any host)

A comma-separated list of hostnames that the Django application will accept requests for. Example:

```
ALLOWED_HOSTS: "budget.example.com,www.budget.example.com"
```

In production, this should list only your actual domain(s). An overly permissive `*` is acceptable on a closed private network but should be tightened for public-facing deployments.

---

### `CSRF_TRUSTED_ORIGINS`

**Default:** *(empty; no extra trusted origins)*

A comma-separated list of origins (scheme + host) that are trusted for CSRF. Required when running behind a reverse proxy that terminates TLS:

```
CSRF_TRUSTED_ORIGINS: "https://budget.example.com"
```

Without this, every form submission (login, expense creation, etc.) will fail with a CSRF verification error when accessed over HTTPS through a proxy.

---

## Database

### `DB_HOST`

**Default:** `127.0.0.1`

Hostname or IP of the MariaDB server. When using Docker Compose with a `mariadb` service, set this to `mariadb` (the service name).

---

### `DB_PORT`

**Default:** `3306`

TCP port of the MariaDB server.

---

### `DB_NAME`

**Default:** `comaney`

Name of the MariaDB database.

---

### `DB_USER`

**Default:** `comaney`

MariaDB login username.

---

### `DB_PASSWORD`

**Default:** `comaney` (insecure placeholder)

MariaDB login password. Change this to a strong random string in production.

---

## Site & URLs

### `SITE_URL`

**Default:** `http://localhost:8080`

The public base URL of your Comaney instance, **without** a trailing slash. This is embedded in outgoing emails (notification links, confirmation links, password reset links). If this is wrong, all email links will point to the wrong address.

```
SITE_URL: "https://budget.example.com"
```

---

## Email

### `DISABLE_EMAILING`

**Default:** *(unset; emailing is enabled)*

Set to `TRUE` (or `1`, `YES`) to suppress all outgoing emails and disable email verification on account registration. When set:

- New users are auto-confirmed without clicking an email link.
- No notification emails are sent for any expense.
- No password reset emails are sent (the forgot-password flow is broken).
- No admin notification emails are sent.

Use this when you have no SMTP server available (development, quick self-hosting). Note that if neither `DISABLE_EMAILING` nor valid `EMAIL_HOST`/`EMAIL_PORT` are set, the application starts in a *system misconfigured* state and shows a banner on every page.

---

### `EMAIL_HOST`

**Default:** `localhost`

SMTP server hostname. Required unless `DISABLE_EMAILING` is set.

---

### `EMAIL_PORT`

**Default:** `1025`

SMTP server port. Required unless `DISABLE_EMAILING` is set.

Common ports:

- `25`: unencrypted SMTP (rarely usable in production)
- `465`: SMTPS (implicit TLS)
- `587`: STARTTLS submission (most common for external SMTP relays)
- `1025`: [Mailpit](https://mailpit.axllent.org/) dev relay (no auth, no TLS)

---

### `EMAIL_USE_TLS`

**Default:** *(unset; TLS disabled)*

Set to `TRUE` to enable STARTTLS. Use with port 587. Do not confuse with implicit TLS (port 465), which Django handles differently.

---

### `EMAIL_HOST_USER`

**Default:** *(empty)*

Username for SMTP authentication. Leave empty for unauthenticated relays (e.g., Mailpit, a local Postfix relay).

---

### `EMAIL_HOST_PASSWORD`

**Default:** *(empty)*

Password for SMTP authentication.

---

### `DEFAULT_FROM_EMAIL`

**Default:** `noreply@comaney.local`

The `From:` address used on all outgoing emails. Should be an address that either does not receive mail or is monitored:

```
DEFAULT_FROM_EMAIL: "Comaney <noreply@budget.example.com>"
```

---

### `ADMIN_NOTIFICATION_EMAIL`

**Default:** *(empty; admin notifications disabled)*

When set, the application sends system notifications to this address:

- When a new user registers.
- When the AI trial API key runs out of funds.
- When a contact form submission is received.

Also, setting this variable (together with `ENABLE_REGISTRATION=TRUE`) enables the contact form at `/contact/`.

---

## Registration

### `ENABLE_REGISTRATION`

**Default:** `FALSE`

Set to `TRUE` to allow new users to create accounts via the registration page. For private single-user or small-group instances, enable this to create your account(s) and then disable it.

When disabled, the registration page returns a 403 and no new accounts can be created.

---

## Demo user

These variables enable a public demo account that visitors can use without signing up. When enabled, a landing page advert is shown and the account is reset automatically by `run_cron` once it has been inactive for at least one week.

Note: the demo banner (shown to any `is_demo` user at every login) is always active regardless of this flag. `ENABLE_DEMO_USERS` only controls the landing page advert, the login gate, and the automatic reset.

### `ENABLE_DEMO_USERS`

**Default:** `FALSE`

Set to `TRUE` to activate the public demo user feature. When set:

- The landing page shows a "try the live demo" advert with the demo email address.
- Demo users can log in. When `FALSE`, any account flagged `is_demo` is denied login (credentials are silently rejected) and existing demo sessions are invalidated.
- `run_cron` runs the automatic reset check.

Requires `DEMO_USER_EMAIL` and `DEMO_USER_PASSWORD` to also be set.

---

### `DEMO_USER_EMAIL`

**Default:** *(empty)*

Email address for the demo account. On reset, `reset_demo_user` deletes all `is_demo` users and creates a fresh account at this address. The account does not need to exist beforehand.

---

### `DEMO_USER_PASSWORD`

**Default:** *(empty)*

Password used when recreating the demo account after a reset.

---

### `DEMO_USER_AI_BUDGET`

**Default:** `0` (use global `AI_TRIAL_USAGE_LIMIT`)

Per-reset AI trial allowance for the demo user, in US cents. Overrides `AI_TRIAL_USAGE_LIMIT` for this account only. Set to a small value (e.g. `10` for $0.10) to limit trial spend per demo cycle. `0` means the global limit applies.

---

## AI / Express Creation

### `AI_TRIAL_API_KEY`

**Default:** *(empty; trial feature disabled)*

An Anthropic API key used as a shared "trial" key for the AI Express Creation feature. Users without their own Anthropic key will use this shared key, subject to `AI_TRIAL_USAGE_LIMIT`.

If empty, only users with their own Anthropic key can use Express Creation.

For single-user instances or private instances where all users have their own key, you do not need to set this.

---

### `AI_TRIAL_USAGE_LIMIT`

**Default:** `0` (cents)

The per-user, per-month spending cap on the shared trial key, in US cents. When a user's share of trial usage reaches this limit in the current calendar month, Express Creation is disabled for that user until the next month.

Example: `AI_TRIAL_USAGE_LIMIT=10` gives each user a $0.10/month allowance on the trial key.

Set to `0` to impose no per-user limit (only the overall Anthropic account budget applies).

---

### `AI_TRIAL_DISABLED_FLAG`

**Default:** `{app_root}/ai_trial_disabled.flag`

Path to the flag file used to indicate that the AI trial feature has been globally disabled (e.g., because the Anthropic account ran out of credit). When this file exists, the trial feature is disabled for all users.

Normally you don't need to set this. Override it if the default path is not writable in your container setup. See [AI Trial Key](ai-trial-key.md) for management instructions.

---

## Public pages

### `PUBLIC_PAGE_IMPRINT_MD`

**Default:** *(unset)*

Path to a Markdown file. When set, a page is added to the site at `/impressum/` with the content of the file, rendered as HTML. Required for hosting a public instance in Germany (legal imprint / Impressum).

```
PUBLIC_PAGE_IMPRINT_MD: /app/legal/impressum.md
```

---

### `PUBLIC_PAGE_EUDATENSCHUTZ_MD`

**Default:** *(unset)*

Path to a Markdown file. When set, a page is added at `/datenschutzerklaerung/` with the rendered content. Required for hosting a public instance subject to GDPR (Datenschutzerklärung / Privacy Policy).

```
PUBLIC_PAGE_EUDATENSCHUTZ_MD: /app/legal/datenschutz.md
```

---

## Performance

### `GUNICORN_WORKERS`

**Default:** `1`

Number of Gunicorn worker processes. Each worker handles one request at a time and holds one database connection. For a single-user private instance, 1 is sufficient. For a multi-user instance under load, use `2 × CPU_cores + 1`.
