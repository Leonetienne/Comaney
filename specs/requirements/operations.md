# Administration and Operations

Sources: `comaney/settings.py`, `comaney/middleware.py`, `comaney/public_pages.py`,
`entrypoint.sh`, management commands, docs `admin-manual/`.

## Configuration and startup

### Environment configuration
`req~operations.env~1`

The system shall take all configuration from environment variables, documented in the admin manual with defaults.

Covers:
- `feat~operations~1`

Tags: Operations

### Secret key in production
`req~operations.secret-key~1`

If `DEBUG` is not `TRUE` and `DJANGO_SECRET_KEY` is unset, then the system shall refuse to start.

Covers:
- `feat~operations~1`

Tags: Security, Operations

### Allowed hosts
`req~operations.allowed-hosts~1`

The system shall accept requests only for hosts in `ALLOWED_HOSTS`, defaulting to any host under `DEBUG` and to none in production.

Covers:
- `feat~operations~1`

Tags: Security, Operations

### Misconfiguration page
`req~operations.misconfigured~1`

If the data directory is not mounted, email is neither configured nor disabled, or the AI provider configuration is invalid, then the system shall answer every request with a misconfiguration page (status 500) explaining what to fix.

Covers:
- `feat~operations~1`

Tags: Operations

### Migrations on start
`req~operations.migrate~1`

When the container starts, the system shall apply pending database migrations and then purge inactive AI provider settings before serving.

Covers:
- `feat~operations~1`

Tags: Operations

### Media volume
`req~operations.media~1`

The system shall store all uploads under `/app/data/media` (avatars, backdrops, project pictures, offline member pictures) and serve them only to logged-in users, with path traversal outside the media root rejected.

Covers:
- `feat~operations~1`

Tags: Security, Operations

### Worker count
`req~operations.workers~1`

The system shall start `GUNICORN_WORKERS` Gunicorn workers (default 1).

Covers:
- `feat~operations~1`

Tags: Operations

## Cron

### run_cron
`req~operations.cron.run~1`

When `run_cron` runs (intended every 5 minutes), the system shall in order materialise recurring expenses, auto-settle due expenses, apply unspent allowance transitions, send due-date notifications, check the demo reset and purge inactive AI settings; `--year` and `--month` shall override the current financial month.

Covers:
- `feat~operations~1`

Tags: Operations

### reset_trial_budgets
`req~operations.cron.trial-reset~1`

When `reset_trial_budgets` runs (intended monthly), the system shall reset all feusers' shared AI spend.

Covers:
- `feat~operations~1`

Tags: Operations

## Management commands

### create_user
`req~operations.cmd.create-user~1`

`create_user <email>` shall create a confirmed, active account with user defaults, taking the password from `-p` or an interactive prompt, optional `--first-name`, `--last-name`, `--demo`, `--ai-trial-budget CENTS` and repeatable `--ai-config KEY=VALUE` for the active provider's user fields; it shall fail without creating anything if the email exists, the password is empty, or an AI setting is unknown, invalid or no provider is active.

Covers:
- `feat~operations~1`

Tags: Operations

### set_user_password
`req~operations.cmd.set-password~1`

`set_user_password <email>` shall set a new password from `-p` or a prompt, and fail for unknown emails.

Covers:
- `feat~operations~1`

Tags: Operations

### remove_user_2fa
`req~operations.cmd.remove-2fa~1`

`remove_user_2fa <email>` shall delete every second factor of the user and clear the recovery code, succeeding idempotently when none exist.

Covers:
- `feat~operations~1`

Tags: Operations

### delete_user
`req~operations.cmd.delete-user~1`

`delete_user <email>` shall delete the account with the same effects as self-service deletion after an interactive "yes", or immediately with `--yes`.

Covers:
- `feat~operations~1`

Tags: Operations

### purge_inactive_ai_config
`req~operations.cmd.purge-ai~1`

`purge_inactive_ai_config` shall delete all users' AI settings of providers other than the active one and do nothing while no provider is active.

Covers:
- `feat~operations~1`

Tags: Operations

## Admin and public pages

### Django admin
`req~operations.admin~1`

The system shall provide the Django admin at `/admin/` for superusers to view and edit users and their second factors.

Covers:
- `feat~operations~1`

Tags: Operations

### Admin notifications
`req~operations.admin-mail~1`

Where `ADMIN_NOTIFICATION_EMAIL` is set and emailing is enabled, the system shall email it on new registrations, shared AI access failures, JSON repairs (unless disabled) and contact form submissions.

Covers:
- `feat~operations~1`

Tags: Operations

### Contact form
`req~operations.contact~1`

Where registration is enabled and `ADMIN_NOTIFICATION_EMAIL` is set, the system shall offer a public contact form at `/contact/` requiring name, email, subject, message and a solved proof-of-work challenge, and email the admin.

Covers:
- `feat~operations~1`

### Legal pages
`req~operations.legal~1`

Where `PUBLIC_PAGE_IMPRINT_MD` or `PUBLIC_PAGE_EUDATENSCHUTZ_MD` points to a Markdown file, the system shall render it publicly at `/impressum/` or `/datenschutzerklaerung/` and link it in the footer.

Covers:
- `feat~operations~1`

### Documentation site
`req~operations.docs~1`

The system shall serve the built documentation at `/docs/`.

Covers:
- `feat~operations~1`

### Credits page
`req~operations.credits~1`

The system shall list attributions for bundled third-party assets on `/credits/`, linked from the footer.

Covers:
- `feat~operations~1`

### Version display
`req~operations.version~1`

The system shall show `APP_VERSION` in the footer.

Covers:
- `feat~operations~1`
