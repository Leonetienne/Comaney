# Comaney: Claude Code Guide

## What this is
Django budgeting app. Session-based auth (no Django auth backend). MariaDB. SCSS + Alpine.js compiled via Node. Deployed as Docker container.

## Rules
- Never use the em-dash character '—' anywhere. Use ':', ';', ',', or rewrite the sentence instead.
- You never commit
- You never publish or push
- All you do is analyze and modify, delete or create files and/or run/read commands, resp. their output.
- If you change any feature covered by readme.md, claude.md, or the docs (docs/src/), you must correct those files
- If you add an important feature, you must also brief it in claude.md and update the relevant docs page(s)
- If you add functional features or fixes, you must cover them with tests.
- End-2-end tests should test the UI. The API may be used for setup and teardown. Whether API verification is acceptable depends on what the test is asserting: if the test is about "does the result appear correctly in the UI", it must verify via the UI. If the test is about "can the UI perform action X" and the API is independently tested elsewhere, API verification is acceptable. For example: "test if the tag list shows the tag" MUST verify via the UI. "Test if the UI can create a tag" may verify via the API if the API is already covered by its own tests. "Test if tag can be deleted" may use the API to create the tag (setup), delete via the UI, then verify via the UI.

## Stack
- **Python 3.12**, Django, Gunicorn, WhiteNoise, mysqlclient
- **Node** (SCSS + JS build only, stripped from final image)
- **Templates**: Django templates in `templates/`
- **SCSS**: source in `build/scss/`, compiled to `static/dist/main.css`.
- **JS**: source in `build/js/`, bundled via esbuild to `static/dist/`.
  - `build/js/expenses.js`: Alpine.js v3 component for the expense list (live search, bulk actions, sum). Bundled with `--target=es2020` (required; lower targets break Alpine's async evaluator).
  - `build/js/dashboard.js`: Alpine.js v3 + Chart.js component for the modular dashboard. Separate bundle (`npm run build:dashboard`) -> `static/dist/dashboard.js`.
- **Building assets**: always use `build/build-assets.sh`; runs `npm install && npm run build` inside a `node:25.9.0-slim` linux/amd64 container. Never run npm directly on the host; `package-lock.json` is gitignored to prevent arch-specific binaries (Mac arm64 vs. linux/amd64) from being committed. The Dockerfile also runs `npm install` fresh inside the linux/amd64 build container.
- **CSS theming**: light/dark mode via CSS custom properties (`--var`). Never replace them with SCSS `$vars`; those are compile-time only. Required for dynamic dark/light mode in-browser.
- **Tests**: Every functional feature requires selenium end-to-end tests, which are in `tests/`. Don't run them yourself!

## App layout
```
feusers/        Auth, profiles, TOTP, API keys
  views/        Package: auth.py · account.py · totp.py
  utils.py      _get_session_feuser, _record_login, PoW helpers
budget/         Expenses, dashboard, scheduled, categories, AI
  views/        Package: dashboard.py · expenses.py · scheduled.py
                         categories_tags.py · express.py · dashboard_cards_api.py
  views/_period.py  Shared request-parsing nav helpers
  dashboard_cards.py  YAML parsing, data computation, sandboxed Python for custom cells
  notifications.py  Notification class logic + cron helpers
  ai_trial.py   Trial key budget tracking + admin notifications
  expense_factory.py  create_expense() - always use this, not Expense() directly
  date_utils.py  financial_month_range / financial_year_range
  decorators.py  @feuser_required - sets request.feuser
api/            REST API (Bearer token auth)
  views.py      View functions only
  serializers.py  _expense_json, _scheduled_json, _apply_*_fields, _set_tags
  utils.py      _err, _ok, _require_auth, _parse_body, _parse_month
comaney/        Settings, root urls, middleware, public_pages context processor
  middleware.py  LastSeenMiddleware (5-min throttle) · SystemMisconfiguredMiddleware
```

## Auth model
- `FeUser` (feusers/models.py): custom user, not `django.contrib.auth.User`
- Login sets `request.session["feuser_id"]`; `_get_session_feuser(request)` loads it
- TOTP: `totp_pending_id` session key during 2FA step
- REST API: Bearer token → `FeUser.api_key`

## Key conventions
- **No Django auth backend**: never use `request.user`, `login()`, `@login_required`
- **Migrations**: `./venv/bin/python3 manage.py makemigrations` locally to generate the file, then `docker compose restart web`; the entrypoint runs `migrate` automatically on start
- **Notification classes**: `"" < soon < tomorrow < today < late < settled`; each sent at most once per expense
- **CSV export** (feusers/views/account.py): dynamic via `_meta.concrete_fields`; skip `owning_feuser`; mask `anthropic_api_key`; resolve `category` FK and `tags` M2M via `extra=`
- **AI express creation**: system prompt in `budget/views/express.py`; expects `{"result":"good","items":[]}` or `{"result":"fail","msg":""}`; never prose
- **Modular dashboard** (`budget/dashboard_cards.py`, `budget/views/dashboard_cards_api.py`):
  - Cards stored as `DashboardCard` model (per user) with only `yaml_config` + `created_at` DB fields. All layout info (`position`, `width`, `height`) lives inside the YAML `positioning:` block. An optional `positioning.mobile:` sub-block (`position`, `width`, `height`) overrides the desktop values on the 6-column mobile grid.
  - YAML fields: `type` (`cell` | `bar-chart` | `pie-chart` | `list` | `line-chart`), `title`, `query`, `group`, `method`, `flip_signs`, `color`, `color_lightmode`, `color_darkmode`, `color_breakpoints`, `link`, `link_template`, `template`, `python`, `order_by`, `order_dir`, `type_colors`, `show_sum`, `sum_template`, `series`, `positioning`.
  - `parse_card_config(yaml_str)` validates and normalises YAML. `compute_card_data(config, qs, feuser, period_info=None)` returns data for the current period; `period_info = {'start': date, 'end': date, 'mode': 'month'|'year'}` is required for line-chart cards.
  - `method` meaning is per card type: cells use `sum`, `total`, `count`, `custom`; bar/pie charts use `sum`, `total`; list cards use `sum`, `total`, `count` (controls the optional sum row); line-chart cards use `base` (per-bucket) or `cum` (cumulative running total, default).
  - `flip_signs: true` multiplies the computed value/sum by -1 (works for cells, charts, and list sum row). For line-chart cards, `flip_signs` is a per-series field that negates that series' values only.
  - `type` (`list`): scrollable table of individual expenses. `order_by` (`value`|`date`|`title`, default `date`), `order_dir` (`asc`|`desc`, default `desc`). `type_colors: false` disables per-row type colouring. `show_sum: true` adds a sum row at the top (coloured green/red by sign unless `type_colors: false` or `method: count`). `sum_template` works like `template` on cell cards, using `$VALUE`/`$CURRENCY_SYMBOL`.
  - `type` (`line-chart`): plots one or more data series over time. `series:` is a required list; each entry has `label` (required), `query` (optional, per-series filter), `method: sum|total` (per-series aggregation, default `sum`), `flip_signs: true` (optional, negates this series' values only), `link_template` (optional, URL with `$START_DATE`/`$END_DATE` substituted on click), `color` (optional hex). Card-level `method: base|cum` controls bucket strategy: `base` shows per-bucket activity only; `cum` builds a cumulative running total (default). Month view: 1 bucket per day; year view: 1 bucket per week (7-day intervals from period start). Buckets generated up to `min(period_end, today)`. API response includes `bucket_starts` (parallel to `labels`) with the first day of each bucket. Chart.js renders a `line` chart; X axis uses sparse `DD. Mon` labels at an angle.
  - `method: custom` cells execute user Python in a sandboxed `exec()`: no imports, no dunder attrs, builtins restricted to safe math + `Decimal`. Runs in a daemon thread with 2 s timeout. Provides `query_sum`, `query_sum_abs`, `query_sum_gt0`, `query_sum_lt0` helpers.
  - `color_lightmode` / `color_darkmode` override `color` per scheme, resolved at page-load via `matchMedia`.
  - `color_breakpoints` (cell only): list of `{less_than, color, color_lightmode, color_darkmode}` objects. Evaluated in order against the computed value; **last matching** breakpoint wins. Each breakpoint overrides the base color when `value < less_than`. Per-breakpoint `color_lightmode`/`color_darkmode` work like on the card root.
  - `link` (cell): clicking the cell body navigates to the URL. `link_template` (charts): clicking a segment navigates, replacing `$GROUP_NAME` with `encodeURIComponent(label)`; `Uncategorized` → `none`.
  - `template` (cell): display string with `$VALUE` and `$CURRENCY_SYMBOL` placeholders. Defaults to `$VALUE $CURRENCY_SYMBOL`. When set, the entire cell content is the rendered string (no separate currency span).
  - API (session auth, not Bearer): `GET/POST /budget/dashboard/cards/`, `PATCH/DELETE /budget/dashboard/cards/<id>/`, `PATCH /budget/dashboard/cards/<id>/resize/`, `POST /budget/dashboard/cards/reorder/`, `GET /budget/dashboard/cards/presets/`, `POST /budget/dashboard/cards/reset/`.
  - Frontend: Alpine.js `dashboardBoard` component in `build/js/dashboard.js`. CSS Grid (12 cols desktop / 6 cols mobile, fixed `ROW_H = 90 px`). HTML5 drag-drop for reorder; pointer-event resize handle; both update `positioning.mobile.*` when on mobile (≤ 6-col grid), `positioning.*` on desktop. Card visual order on mobile is applied via CSS `order` (DOM order always reflects desktop `position`). Chart.js for bar/pie/line-chart cards. CodeMirror 6 YAML editor in both modals. In-DOM `window.confirmDialog()` for delete and preset-overwrite confirmations. Modals do not close on outside click.
- **Expense search query parser** (`budget/query_parser.py`): translates the search bar's mini-language into Django Q objects via `apply_query(qs, query_str)`. Called by the API expense list view. Supported filters: `type=`, `settled=`, `deactivated=`, `value` (with `< <= > >= = ==`), `date` (date comparisons, formats `dd.mm.yyyy` / `mm/dd/yyyy` / `yyyy-mm-dd`, magic words `today`, `cur_week_start` (Monday of current week), `cur_week_end` (Sunday of current week)), `cat=` / `tag=` (substring or `none` for null), `payee=`, free-text, `||` OR, `()` grouping, `!` NOT prefix. The full query string is lowercased before parsing.

## Documentation
mkdocs/Material sources live in `docs/src/`. Built site goes to `docs/build/site/` and is served by Django at `/docs/` (via `django.views.static.serve` in `comaney/urls.py`).
Build: `./docs/build/build-docs.sh` (uses Docker; requires Docker daemon).
Chapters: Introduction · User Manual · Admin Manual · Developer Manual.

## Running tests
Two test suites exist under `tests/`:

**Unit tests** (no Docker, no browser, pure Python):
```bash
venv/bin/pytest tests/unit/ -v
```

**End-to-end tests** (Selenium + requests against a live Docker stack):
```bash
# Stack must be running: docker compose up
# Mailpit at :8030, app at :8080
cd tests/e2e && pytest -x
```
- `DOCKER_WEB = "comaney-web-1"` (e2e/conftest.py)
- E2E tests numbered by prefix; run in order
- `run_cmd("management_command")` via docker exec
- `ctx` dict is session-scoped state shared across tests in a file
- **NEVER use `wait_url`, `wait_text`, or any `w.until(...)` / `WebDriverWait` condition after a browser action.** Always use `time.sleep()` and then assert on `driver.page_source` or `driver.current_url`. Conditional waits cause race conditions.
- Pure algorithm logic (no Django/DB) goes in `tests/unit/`. Use `venv/bin/pytest tests/unit/` to run them without the Docker stack.

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

## Management commands
- `create_user <email> [-p <password>]`: creates a confirmed, active user account; prompts for password if `-p` is omitted (feusers/management/commands/create_user.py)
- `set_user_password <email> [-p <password>]`: updates the password for an existing user; prompts if `-p` is omitted (feusers/management/commands/set_user_password.py)
- `remove_user_2fa <email>`: clears TOTP fields so the user can log in with password only; idempotent (feusers/management/commands/remove_user_2fa.py)
- `delete_user <email> [--yes]`: permanently deletes a user and all associated data; prompts for confirmation unless `--yes` is given (feusers/management/commands/delete_user.py)

## Cron jobs
Two management commands must run on a schedule inside the container:
- `run_cron`: every 5 minutes (fires notifications, auto-settles, carry-overs)
- `reset_trial_budgets`: monthly (resets AI trial usage per user)

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
