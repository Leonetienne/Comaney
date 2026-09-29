# Implementing Agent Onboarding: Scheduled Expense Materialization Integrity

You are implementing the "Scheduled Expense Materialization Integrity" feature
in the Comaney Django application at `/Users/agent/private-work/Comaney/`.

**Your single source of truth is `scheduled-integrity-spec.md`** in the
project root. Read it first and follow it precisely. The spec was written
after a thorough review of the existing code and a multi-turn design
discussion with the project owner; it reflects exact decisions already
confirmed, plus one explicitly flagged open question (§6).

---

## What this feature does (in one paragraph)

`generate_scheduled_expenses.py` currently deduplicates materialized expenses
by matching `date_due`, which is user-editable — hand-correcting a generated
expense's due date, or editing the schedule's own recurrence rule (which
triggers regeneration *synchronously* on save), both cause duplicate expenses
today. This feature replaces date-based dedup with a stable, immutable
`Expense.scheduled_occurrence_date` identity, adds a `ScheduledExpense.last_run`
(financial-year) ratchet so a schedule is only ever materialized once per
year, and locks the two recurrence field groups (`repeat_every_factor`/`unit`,
and `repeat_base_date`/`end_on`) behind separate, explicitly-confirmed,
server-verified checkboxes — editing either group without confirmation is
silently discarded server-side regardless of what the client submits.

**First, resolve §6 with the project owner before touching the REST API** —
do not assume an answer.

---

## Key files to read before touching anything

- `budget/management/commands/generate_scheduled_expenses.py` — the
  materializer; core algorithm rewrite is here (spec §3)
- `budget/models/scheduled_expense.py` — add `last_run`
- `budget/models/expense.py` — add `scheduled_occurrence_date`
- `budget/views/scheduled.py` — `scheduled_edit`, `scheduled_create`,
  `_generate_and_notify`; gate logic goes here (spec §4)
- `budget/date_utils.py` — `current_financial_month`, `financial_year_range`
  (already exist, reuse as-is)
- `budget/management/commands/auto_settle_expenses.py` — reference for the
  `<= today` cutoff semantics the auto-settle-on-create extra should mirror
- `budget/templates/budget/scheduled_form.html` — field locking, checkboxes,
  moving `default_auto_settle_on_due_date` (spec §5)
- `templates/base.html` — reuse `window.confirmDialog(message, okLabel)`;
  do not build a new modal component
- `api/views/` (find the `ScheduledExpense` viewset/view) — only touch after
  §6 is resolved

---

## Critical rules (from CLAUDE.md)

- Never use em-dash. Use colon, semicolon, or rewrite.
- Never commit or push.
- New functional features or fixes must add tests.
- Always use `expense_factory.create_expense()` for new expenses; never
  `Expense()` directly.
- Auth: use `request.session["feuser_id"]` / `@feuser_required`. Never
  `request.user`.
- Migrations: `./venv/bin/python3 manage.py makemigrations` to generate, then
  `docker-compose exec web python manage.py migrate` to apply.
- E2E tests: use `time.sleep()` then assert. Never `WebDriverWait.until()`
  after browser actions. Use `execute_script` for filling inputs. Use XPath
  text match for buttons. Never `form button[type=submit]` as a selector;
  scope to the form's container.
- Run tests with `-v` piped through `tee logfile.log`.

---

## Implementation order

1. **Models**: `Expense.scheduled_occurrence_date`, `ScheduledExpense.last_run`.
   Generate migration.
2. **Data migration** (spec §7): backfill `last_run` for every existing
   non-deactivated schedule from `current_financial_month(...)`; backfill
   `scheduled_occurrence_date = date_due` for existing generated expenses.
   This must ship in the same deploy as step 1 — do not defer it.
3. **`generate_scheduled_expenses.py`**: rewrite per spec §3 (gate on
   `last_run`, dedup by `scheduled_occurrence_date`, prune out-of-window rows,
   auto-settle-on-create extra, set `last_run` on non-`--year` runs).
4. **`views/scheduled.py`**: `scheduled_edit` gate logic per spec §4
   (snapshot pre-edit values, sanitize POST for unconfirmed gates, Gate A
   wipe, Gate B forced regen via `last_run = None`).
5. **Template + JS** per spec §5: disabled-by-default field groups showing
   current values, two checkboxes with `confirmDialog`, submit-time
   re-enable-before-serialize, uncheck-resets-to-original-and-redisables,
   move the auto-settle checkbox.
6. **Resolve §6**, then implement REST API changes if confirmed.
7. **Tests** per spec §8: modify the two named e2e tests (plus the API test
   if §6 says to), add all the new tests listed, no deletions expected.
8. **Docs**: update `docs/src/docs/user-manual/` if a scheduled-expense page
   exists, per spec §9.

---

## Test commands

Unit tests (no Docker):
```
venv/bin/pytest tests/unit/ -v | tee logfile.log
```

E2E tests (require live stack at :8080, Mailpit at :8030):
```
pytest -sxv | tee logfile.log
```

Targeted re-runs while iterating:
```
pytest -sxv tests/e2e/scheduled/ -v | tee logfile.log
pytest -sxv tests/e2e/api/test_api.py -v | tee logfile.log
```

---

## Things to be careful about

- The prune step in §3 step 6 is generic — it runs on every actual
  regeneration pass, not just Gate B edits. Don't special-case it per gate;
  it's naturally inert when nothing is out of window.
- Gate A's wipe is a separate, explicit, unconditional delete — do not try to
  make the generic prune logic handle it too. A coincidental date overlap
  between old and new occurrence sets must still be wiped under Gate A; the
  generic prune would incorrectly spare it.
- Resetting `last_run = None` on a single schedule before calling
  `_generate_and_notify` only forces *that* schedule through the gate for
  this one request — do not touch `last_run` on any other schedule in the
  same batch.
- Don't skip the migration-safety backfill in step 2. Without it, the first
  cron tick after deploy regenerates and re-notifies for every schedule in
  the system at once.
- `scheduled_occurrence_date` is never exposed in a form or API response —
  it's an internal key only.
