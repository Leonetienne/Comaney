# Comaney — Claude Code Guide

## What this is
Django budgeting app. Session-based auth (no Django auth backend). MariaDB. SCSS compiled via Node. Deployed as Docker container.

## Rules
- You never commit
- You never publish or push
- All you do is analyze and modify, delete or create files and/or run/read commands, resp. their output.
- If you change any feature covered by readme.md or claude.md, you must correct these .md files
- If you add an important feature, you must also brief it in claude.md
- If you add functional features or fixes, you must cover them with tests.

## Stack
- **Python 3.12**, Django, Gunicorn, WhiteNoise, mysqlclient
- **Node** (SCSS → CSS build only, stripped from final image)
- **Templates**: Django templates in `templates/`
- **SCSS**: source in `build/scss/`, compiled to `static/dist/main.css`. Run `npm run build:css` after SCSS changes (or `npm run watch:css` during dev). Use `nvm install` first to get the right Node version.
- **CSS theming**: light/dark mode via CSS custom properties (`--var`). Never replace them with SCSS `$vars` — those are compile-time only. Required for dynamic dark/light mode in-browser.
- **Tests**: Every functional feature requires selenium end-to-end tests, which are in `tests/`. Don't run them yourself!

## App layout
```
feusers/        Auth, profiles, TOTP, API keys
  views/        Package: auth.py · account.py · totp.py
  utils.py      _get_session_feuser, _record_login, PoW helpers
budget/         Expenses, dashboard, scheduled, categories, AI
  views/        Package: dashboard.py · expenses.py · scheduled.py
                         categories_tags.py · express.py
  views/_period.py  Shared request-parsing nav helpers
  notifications.py  Notification class logic + cron helpers
  ai_trial.py   Trial key budget tracking + admin notifications
  expense_factory.py  create_expense() — always use this, not Expense() directly
  date_utils.py  financial_month_range / financial_year_range
  decorators.py  @feuser_required — sets request.feuser
api/            REST API (Bearer token auth)
  views.py      View functions only
  serializers.py  _expense_json, _scheduled_json, _apply_*_fields, _set_tags
  utils.py      _err, _ok, _require_auth, _parse_body, _parse_month
comaney/        Settings, root urls, middleware, public_pages context processor
  middleware.py  LastSeenMiddleware (5-min throttle) · SystemMisconfiguredMiddleware
```

## Auth model
- `FeUser` (feusers/models.py) — custom user, not `django.contrib.auth.User`
- Login sets `request.session["feuser_id"]`; `_get_session_feuser(request)` loads it
- TOTP: `totp_pending_id` session key during 2FA step
- REST API: Bearer token → `FeUser.api_key`

## Key conventions
- **No Django auth backend** — never use `request.user`, `login()`, `@login_required`
- **Migrations**: `./venv/bin/python3 manage.py makemigrations` locally to generate the file, then `docker compose restart web` — the entrypoint runs `migrate` automatically on start
- **Notification classes**: `"" < soon < tomorrow < today < late < settled` — each sent at most once per expense
- **CSV export** (feusers/views/account.py): dynamic via `_meta.concrete_fields`; skip `owning_feuser`; mask `anthropic_api_key`; resolve `category` FK and `tags` M2M via `extra=`
- **AI express creation**: system prompt in `budget/views/express.py`; expects `{"result":"good","items":[]}` or `{"result":"fail","msg":""}` — never prose

## Running tests
Tests are end-to-end Selenium + requests against a live Docker stack.
```bash
# Stack must be running: docker compose up
# Mailpit at :8030, app at :8080
cd tests && pytest -x
```
- `DOCKER_WEB = "comaney-web-1"` (conftest.py)
- Tests numbered by prefix — run in order
- `run_cmd("management_command")` via docker exec
- `ctx` dict is session-scoped state shared across tests in a file

## Docker / build
```bash
docker buildx build \
  --platform linux/amd64 \
  -f Deployment/Dockerfile \
  -t leonetienne/comaney:0.1.0/<change version!!, could also be "latest"> \
  --build-arg APP_VERSION=0.1.0<change version!!> \
  --push \
  .
```
`APP_VERSION` baked in at build time → shown in footer via `{{ APP_VERSION }}` context processor.
However, please, never build or publish images yourself.

Create superuser: `docker exec -it <container> python manage.py createsuperuser`

Re-enable AI trial key after limit hit: `/admin/ai-trial/` in the admin.

## Cron jobs
Two management commands must run on a schedule inside the container:
- `run_cron` — every 5 minutes (fires notifications, auto-settles, carry-overs)
- `reset_trial_budgets` — monthly (resets AI trial usage per user)

## Settings env vars (key ones)
| Var | Purpose |
|-----|---------|
| `DJANGO_SECRET_KEY` | required in prod |
| `DEBUG` | `TRUE` for dev mode |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | MariaDB connection |
| `ENABLE_REGISTRATION` | `TRUE` to allow signups |
| `ADMIN_NOTIFICATION_EMAIL` | enables contact form (requires `ENABLE_REGISTRATION` too) |
| `DISABLE_EMAILING` | `TRUE` for no-email dev mode |
| `EMAIL_HOST` / `EMAIL_PORT` | required unless above set |
| `EMAIL_USE_TLS` | `TRUE` to enable TLS |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | SMTP credentials |
| `DEFAULT_FROM_EMAIL` | sender address |
| `AI_TRIAL_API_KEY` / `AI_TRIAL_USAGE_LIMIT` | shared trial key (cents) |
| `SITE_URL` | used in email links |
| `PUBLIC_PAGE_IMPRINT_MD` / `PUBLIC_PAGE_EUDATENSCHUTZ_MD` | optional static MD pages |
| `APP_VERSION` | shown in footer |
| `GUNICORN_WORKERS` | number of Gunicorn workers (default: 1) |
