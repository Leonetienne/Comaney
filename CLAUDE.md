# Comaney: Agent Reference

## Rules
- Never use em-dash '—'; use ':', ';', or rewrite
- Never commit, push, or publish
- Only analyze, modify, create, or delete files and run commands
- Updating a feature: keep CLAUDE.md, AGENTS.md, and docs/src/ in sync
- New functional features or fixes: must add tests
- Always code in a way a human can maintain it!
- Use best practices, Don't repeat yourself (DRY), clear architecture

## Stack
- Python 3.12, Django, Gunicorn, WhiteNoise, mysqlclient, MariaDB
- SCSS: `build/scss/` -> `static/dist/main.css`
- JS: `build/js/` -> `static/dist/` via esbuild
  - `expenses.js`: Alpine.js v3, bundled `--target=es2020` (required)
  - `dashboard.js`: Alpine.js v3 + Chart.js
- Build assets: `build/build-assets.sh` (Docker container, never run npm directly on host)
- CSS theming: CSS custom properties (`--var`) only, never SCSS `$vars` (breaks dark mode)

## Auth
- Custom `FeUser` model, not `django.contrib.auth.User`
- Session key: `request.session["feuser_id"]`; load via `_get_session_feuser(request)`
- Never use `request.user`, `login()`, or `@login_required`
- REST API: Bearer token -> `FeUser.api_key`

## App layout
```
feusers/       Auth, profiles, TOTP, API keys
budget/        Expenses, dashboard, scheduled, categories, AI
  expense_factory.py  create_expense() -- always use this, never Expense() directly
  dashboard_cards.py  YAML parsing + data computation
  decorators.py       @feuser_required
buddies/       Projects, buddy system, settlements
  services/    BuddyArchiveService, ProjectService (alias BuddyGroupService), etc.
  urls.py      /buddies/ namespace
  urls_projects.py  /projects/ namespace
api/           REST API (Bearer token auth)
comaney/       Settings, root urls, middleware
```

## Key conventions

**Projects** (`buddies/`): renamed from "Buddy Groups"; DB aliases still exist. `Expense.project` FK links to project. Call `project.update_lastmod()` on every mutation. Solo projects hide debt graph, pie chart, and settlement sections. Archived projects block mutations except confirming in-flight settlements.

**Achim Archive**: removing a DummyUser merges their history into a special `is_archive=True` dummy instead of deleting it. Service: `BuddyArchiveService` in `buddies/services/archive.py`.

**Settlements**: debtor creates with `settled=True, buddy_approved=False`; balance clears only when creditor confirms (`buddy_approved=True`). Settlement expenses must never appear in "Did you pay for this?" (`pending_as_expense_owner` filters `settled=False`).

**Migrations**: `./venv/bin/python3 manage.py makemigrations` to generate, then `docker-compose exec web python manage.py migrate` to apply.

**Query parser** (`budget/query_parser.py`): `apply_query(qs, query_str)`. Filters: `type=`, `settled=`, `deactivated=`, `value` (comparisons), `date` (dd.mm.yyyy / mm/dd/yyyy / yyyy-mm-dd, magic: `today`, `cur_week_start`, `cur_week_end`), `cat=`, `tag=`, `payee=`, `project=`, free-text, `||` OR, `()` grouping, `!` NOT.

**AI express creation**: prompt in `budget/views/express.py`; JSON response only: `{"result":"good","items":[]}` or `{"result":"fail","msg":""}`. Items may include `project_uid`. Catalog via `_build_catalog()` (categories, tags, non-archived projects).

**Dashboard cards** (`budget/dashboard_cards.py`): stored as `DashboardCard` with `yaml_config` only; all layout in YAML `positioning:` block. Types: `cell`, `bar-chart`, `pie-chart`, `list`, `line-chart`, `gauge`. API uses session auth (not Bearer): `GET/POST /budget/dashboard/cards/`, `PATCH/DELETE /budget/dashboard/cards/<id>/`. AI card assist (`budget/dashboard_card_ai.py`, `POST /budget/dashboard/cards/ai/`): generates/edits a card's YAML from a free-text prompt; system prompt is built live from `docs/src/docs/user-manual/dashboard/` (all child pages) plus the user's catalog and their other cards' YAML, so it stays in sync with the docs automatically. Gated by `ai_smart_create_available` (context processor) and per-user trial exhaustion; result only fills the YAML editor, never auto-saves.

**Notification classes** (ordered): `"" < soon < tomorrow < today < late < settled`; each sent at most once per expense.

## Tests
- Always run tests with `-v` and pipe through `tee logfile.log`

**Unit** (no Docker): `venv/bin/pytest tests/unit/ -v | tee logfile.log`

**E2E** (Selenium + live stack at :8080, Mailpit at :8030): `pytest -sxv | tee logfile.log`
- E2E tests numbered by prefix; `ctx` dict is session-scoped shared state
- `run_cmd("management_command")` executes via docker exec into `comaney-web-1`
- NEVER use `WebDriverWait` / `w.until()` after browser actions; always `time.sleep()` then assert
- UI assertions: must verify via UI (not just API) when the test is about what the user sees
- Pure algorithm logic with no Django/DB: goes in `tests/unit/`

## Demo users (`is_demo=True`)

A demo user is a shared public account anyone can log into. Every restriction on a demo user must satisfy two hard rules:

1. **No interaction with real users.** A demo user must never be able to send emails, invitations, partnership requests, or any other out-of-band contact to a real account. Real users must equally be unable to pull a demo account into their social graph (buddy, project member, partner).
2. **No sabotage of the shared demo experience.** A demo user must never be able to perform an action that degrades the demo for the next visitor: they cannot change their own name, email, or password; cannot delete the account; cannot set up 2FA; cannot generate an API key.

What demo users **can** do: change currency, financial month settings, unspent allowance action, create expenses, use AI express entry (subject to `special_ai_trial_budget`).

The demo banner (shown at every login, must be accepted) and all server-side blocks are enforced regardless of `ENABLE_DEMO_USERS`. That flag only gates login access and the landing-page advert. `reset_demo_user` (run by `run_cron`) deletes all `is_demo=True` users and recreates a fresh "Dean Demo" account once the last one has been inactive for a week.

When adding any new feature: if it sends email, modifies another user's data, or lets a user meaningfully alter their own identity/credentials, block it for demo users — both in the view (redirect/403) and in the UI (disabled/hidden).

## Management commands
- `create_user <email> [-p pw] [--demo] [--ai-trial-budget CENTS]`
- `set_user_password <email> [-p pw]`
- `remove_user_2fa <email>`
- `delete_user <email> [--yes]`
- `reset_demo_user` (checks condition and resets demo account; called by `run_cron`)

## Cron
- `run_cron`: every 5 min (notifications, auto-settle, allowance transitions, demo user reset)
- `reset_trial_budgets`: monthly (resets AI trial usage)

## Key env vars
| Var | Purpose |
|-----|---------|
| `DJANGO_SECRET_KEY` | required in prod |
| `DEBUG` | `TRUE` for dev |
| `DB_HOST/PORT/NAME/USER/PASSWORD` | MariaDB |
| `ENABLE_REGISTRATION` | `TRUE` to allow signups |
| `DISABLE_EMAILING` | `TRUE` to skip email in dev |
| `EMAIL_HOST/PORT/USE_TLS/HOST_USER/HOST_PASSWORD` | SMTP |
| `DEFAULT_FROM_EMAIL` | sender address |
| `AI_TRIAL_API_KEY` / `AI_TRIAL_USAGE_LIMIT` | shared trial key (cents) |
| `SITE_URL` | used in email links |
| `APP_VERSION` | shown in footer |
| `GUNICORN_WORKERS` | default 1 |
