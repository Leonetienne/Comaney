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
- Run `docker-compose up -d` to start the stack but it should already be running at http://localhost:8080

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

**Projects** (`buddies/`): renamed from "Buddy Groups"; DB aliases still exist. `Expense.project` FK links to project. Call `project.update_lastmod()` on every mutation. Solo projects hide debt graph, pie chart, and settlement sections. Archived projects block mutations except confirming in-flight settlements. `Project.permission_laxity` (`PERMISSION_LAXITY_ADMIN_ONLY=0` default, `PERMISSION_LAXITY_MEMBERS=1`) governs who may edit name/description/picture: gate all three via `project.can_edit_details(feuser)` (admin always true; other members only when laxity is `MEMBERS`). Admin sets it via a dropdown on the Manage page (`project_set_permission_laxity` view, admin-only). Everything else (invites, transfer, archive, delete) stays admin-only.

**Achim Archive**: removing a DummyUser merges their history into a special `is_archive=True` dummy instead of deleting it. Service: `BuddyArchiveService` in `buddies/services/archive.py`.

**Participant approvals** (`BuddySpending.approval_state`/`consent_set_at`, the Check/X consent shown per-participant): applies equally to direct buddy and project expenses. When the owner edits a shared expense and changes the title, value, participants, or any share, all participants' approvals reset (state -> `APPROVAL_NEUTRAL`, `consent_set_at` -> `None`). Editing only unrelated fields (payee, note, category, date) preserves approvals. The "your approval was reset" note in the update email goes only to participants who had actually approved beforehand (not neutral/rejected). `set_buddy_spendings` always deletes/recreates rows (fresh = reset); `expense_edit` decides reset-vs-preserve via `BuddyExpenseService.spend_signature`/`snapshot_approvals`/`restore_approvals`/`reset_participant_approvals`, and passes `reset_participant_pks` (the previously-approved pks) into `BuddyEmailService.notify_expense_updated`.

**Settlements**: debtor creates with `settled=True, buddy_approved=False`; balance clears only when creditor confirms (`buddy_approved=True`). Settlement expenses must never appear in "Did you pay for this?" (`pending_as_expense_owner` filters `settled=False`).

**Scheduled expenses** (`budget/management/commands/generate_scheduled_expenses.py`): materialization runs on the cron and synchronously on every `ScheduledExpense` create/edit. Dedup key is `Expense.scheduled_occurrence_date` (immutable, never `date_due`, never shown in any form/API). `ScheduledExpense.last_run` (financial year) gates a schedule to materialize at most once per year; `--year` bypasses the gate. `repeat_every_factor`/`repeat_every_unit` (Gate A) and `repeat_base_date`/`end_on` (Gate B) are locked on edit behind `confirm_modify_schedule` / `confirm_modify_schedule_window` (checkbox in the web form, boolean in the API PATCH body); unconfirmed changes to those fields are silently discarded server-side. Confirmed Gate A wipes and regenerates every current-year expense for the schedule (including settled ones); confirmed Gate B forces a regeneration pass that prunes now-out-of-window expenses and adds newly in-window ones, both by resetting `last_run = None` before calling `_generate_and_notify`.

**Migrations**: `./venv/bin/python3 manage.py makemigrations` to generate, then `docker-compose exec web python manage.py migrate` to apply.

**Query parser** (`budget/query_parser.py`): `apply_query(qs, query_str)`. Filters: `type=`, `settled=`, `deactivated=`, `value` (comparisons), `date` (dd.mm.yyyy / mm/dd/yyyy / yyyy-mm-dd, magic: `today`, `cur_week_start`, `cur_week_end`), `cat=`, `tag=`, `payee=`, `project=`, free-text, `||` OR, `()` grouping, `!` NOT.

**AI express creation**: helpers in `budget/express_service.py`, view in `budget/views/express.py`; JSON response only: `{"result":"good","items":[]}` or `{"result":"fail","msg":""}`. The system prompt is assembled from independent feature blocks (`_SMART_CREATE_BASE` + `_SMART_CREATE_PROJECTS`/`_PROJECT_PARTICIPANTS`/`_PROJECT_PAYER`/`_DIRECT_BUDDY`) by `_build_smart_create_system(catalog, blocks=None)`; pass a subset to disable a capability (base is mandatory). `_select_smart_create_blocks(projects_data, single_buddies)` picks that subset per-request to save tokens: no direct buddies drops `_SMART_CREATE_DIRECT_BUDDY`; no non-archived projects drops all project fragments; projects present but none with more than one `ProjectMember` row (owner included) drops `_PROJECT_PARTICIPANTS`/`_PROJECT_PAYER` while keeping `_SMART_CREATE_PROJECTS` (so a solo project can still be picked as `project_uid`). Must be called with the same `projects_data`/`single_buddies` lists used for the catalog (see idx-desync note below), never a fresh query. The AI never sees member/buddy names as identifiers, only 0-based `idx` positions into that request's catalog list (`_build_catalog`), so it cannot reference anyone outside the catalog. Assignment fields (all mutually validated + applied client-side in `express_creation.html`, which presets the buddy section before confirm so the existing confirm path handles them): `project_uid`; project-only `project_participants` (`{idx, included, share_percent}` list, `_sanitize_project_participants` → `applyAiParticipants`) and `project_payer` (member idx, `_sanitize_project_payer` → `applyAiPayer`); direct-buddy `buddy_idx`/`buddy_paid`/`buddy_share_percent` (`_sanitize_direct_buddy` → `applyAiBuddy`; mutually exclusive with `project_uid`). An out-of-range or malformed idx is silently dropped through `_handle_invalid_ai_reference` (single choke point for future graceful correction). Pinned `share_percent` values that would overcommit a project expense (sum > 100, or sum != 100 when every included participant is pinned with none left to auto-absorb the remainder) are proportionally rescaled to sum to 100 via `_normalize_participant_shares`/`_handle_share_sum_mismatch`; a lone remaining participant is always forced to 100%. Catalog via `_build_catalog(feuser, projects_data, single_buddies)` (categories, tags, non-archived projects incl. per-member idx, direct buddies incl. idx); `projects_data`/`single_buddies` MUST be the exact same lists `_buddy_context()` (`budget/views/expenses.py`) built for that request's buddy-widget JS config (`_validate_items` takes the same two args too) -- none of `ProjectMember`, `get_actual_buddies`, or `get_dummy_buddies` have a fully deterministic ordering, so two independent queries can return members/buddies in different order and silently desync the AI's idx from the widget's arrays; reusing one query's result everywhere is what keeps idx valid. On confirm, the success banner's "View expenses" link points to `/buddies/summary/` when every saved expense is a direct buddy expense, to `/projects/<id>/` when they all belong to one project, else the expense list (via `view`/`pid` query params). Entry points: the `.fab-new-expense` FAB (expense list, project detail) opens a `.fab-wrap`/`.fab-menu` submenu (toggle wired globally in `templates/base.html` via `.fab-toggle`/outside-click, styled in `_buddies.scss` as small `.fab-menu-item` circles matching the main FAB's shape, labelled "Manual"/"AI") offering a plain link to the manual form (`title="Create manually"`) vs AI Express (`title="AI Express"`); from a project page the latter links with `?prefill=<urlencoded text>`, which `express_creation` (GET only, ignored on POST) seeds into `context["description"]` so the `.smart-input` textarea opens pre-filled with `Create all expenses for project '<name>'`. Both menu items are plain links gated by `ai_smart_create_available` (AI Express hidden entirely when unavailable), not JS-conditional.

**Dashboard cards** (`budget/dashboard_cards.py`): stored as `DashboardCard` with `yaml_config` only; all layout in YAML `positioning:` block. Types: `cell`, `bar-chart`, `pie-chart`, `list`, `line-chart`, `gauge`. API uses session auth (not Bearer): `GET/POST /budget/dashboard/cards/`, `PATCH/DELETE /budget/dashboard/cards/<id>/`. AI card assist (`budget/dashboard_card_ai.py`, `POST /budget/dashboard/cards/ai/`): generates/edits a card's YAML from a free-text prompt; system prompt is built live from `docs/src/docs/user-manual/dashboard/` (all child pages) plus the user's catalog and their other cards' YAML, so it stays in sync with the docs automatically. Gated by `ai_smart_create_available` (context processor) and per-user trial exhaustion; result only fills the YAML editor, never auto-saves.

**Notification classes** (ordered): `"" < soon < tomorrow < today < late < settled`; each sent at most once per expense.

**Double-submit guard** (`templates/base.html`): a global `document` `submit` listener disables every submit button in a form (`.is-loading` class, styled in `_buttons.scss`) the moment a submit event isn't cancelled, so a stray second click can't re-fire the same create/save action before the page navigates away. Applies automatically to any plain form; pages that intercept `submit` themselves (buddy consent AJAX, the date-range-warning confirm dialogs in `expense_form.html`/`express_creation.html`) call `e.preventDefault()` first, which the guard checks (`e.defaultPrevented`) and skips, leaving those flows to lock the button on their own eventual real submit. No per-page wiring needed for new create/save buttons.

## Tests
- Always run tests with `-v` and pipe through `tee logfile.log`
- Only ever pass `-v`. NEVER use `-x`: it stops at the first failure, which hides
  the full picture and breaks expected-to-fail regression runs.

**Unit** (no Docker): `venv/bin/pytest tests/unit/ -v | tee logfile.log`

**E2E** (Selenium + live stack at :8080, Mailpit at :8030): `pytest -v | tee logfile.log`
- E2E tests numbered by prefix; `ctx` dict is session-scoped shared state
- `run_cmd("management_command")` executes via docker exec into `comaney-web-1`
- `AI_API_KEY_TESTS` env var (host side, read by `tests/e2e/helpers.py`): if set, every test account created via `setup_user`/`create_confirmed_user`/`ai_test_api_key_args()` call sites gets it as its own `anthropic_api_key` at creation time, so AI spend during e2e runs is billed on a dedicated key instead of the app's shared trial key. Demo-account creations (`--demo`) and `test_management_commands.py`/`test_demo_user.py` deliberately skip this (it would interfere with trial-budget behavior they test).
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
- `create_user <email> [-p pw] [--demo] [--ai-trial-budget CENTS] [--anthropic-api-key KEY]`
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
| `ALLOWED_HOSTS` | comma-separated; `*` only under DEBUG, empty (must configure) in prod |
| `APP_VERSION` | shown in footer |
| `GUNICORN_WORKERS` | default 1 |

## Transport / TLS
This app is ALWAYS deployed behind a reverse proxy that terminates TLS and forwards
plain HTTP to Gunicorn. The app itself expects HTTP and does NOT enforce HTTPS in any
way: it never redirects HTTP->HTTPS, never emits HSTS, and never inspects
`X-Forwarded-Proto`. HTTP->HTTPS redirection and HSTS belong on the proxy, not here.
Do not add `SECURE_SSL_REDIRECT`, `SECURE_HSTS_*`, or `SECURE_PROXY_SSL_HEADER`:
enabling app-side HTTPS redirect behind an SSL-terminating proxy causes an infinite
301 redirect loop. When `DEBUG` is off, the only transport hardening the app applies is
marking the session and CSRF cookies `Secure` (safe because the public edge is HTTPS).
