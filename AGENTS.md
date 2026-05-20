# Comaney: Agent Reference

## Rules
- Never use em-dash '—'; use ':', ';', or rewrite
- Never commit, push, or publish
- Only analyze, modify, create, or delete files and run commands
- Updating a feature: keep CLAUDE.md, AGENTS.md, and docs/src/ in sync
- New functional features or fixes: must add tests

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

**Migrations**: `./venv/bin/python3 manage.py makemigrations` then `docker compose restart web` (entrypoint runs `migrate` on start).

**Query parser** (`budget/query_parser.py`): `apply_query(qs, query_str)`. Filters: `type=`, `settled=`, `deactivated=`, `value` (comparisons), `date` (dd.mm.yyyy / mm/dd/yyyy / yyyy-mm-dd, magic: `today`, `cur_week_start`, `cur_week_end`), `cat=`, `tag=`, `payee=`, `project=`, free-text, `||` OR, `()` grouping, `!` NOT.

**AI express creation**: prompt in `budget/views/express.py`; JSON response only: `{"result":"good","items":[]}` or `{"result":"fail","msg":""}`. Items may include `project_uid`. Catalog via `_build_catalog()` (categories, tags, non-archived projects).

**Dashboard cards** (`budget/dashboard_cards.py`): stored as `DashboardCard` with `yaml_config` only; all layout in YAML `positioning:` block. Types: `cell`, `bar-chart`, `pie-chart`, `list`, `line-chart`. API uses session auth (not Bearer): `GET/POST /budget/dashboard/cards/`, `PATCH/DELETE /budget/dashboard/cards/<id>/`.

**Notification classes** (ordered): `"" < soon < tomorrow < today < late < settled`; each sent at most once per expense.

## Tests
**Unit** (no Docker): `venv/bin/pytest tests/unit/ -v`

**E2E** (Selenium + live stack at :8080, Mailpit at :8030): `pytest -sx`
- E2E tests numbered by prefix; `ctx` dict is session-scoped shared state
- `run_cmd("management_command")` executes via docker exec into `comaney-web-1`
- NEVER use `WebDriverWait` / `w.until()` after browser actions; always `time.sleep()` then assert
- UI assertions: must verify via UI (not just API) when the test is about what the user sees
- Pure algorithm logic with no Django/DB: goes in `tests/unit/`

## Management commands
- `create_user <email> [-p pw]`
- `set_user_password <email> [-p pw]`
- `remove_user_2fa <email>`
- `delete_user <email> [--yes]`

## Cron
- `run_cron`: every 5 min (notifications, auto-settle, carry-overs)
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
