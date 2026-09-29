# Spec: Scheduled Expense Materialization Integrity

## Summary

Scheduled expenses are materialized into real `Expense` rows by
`generate_scheduled_expenses.py`, which runs both on a 5-minute cron
(`run_cron`) and **synchronously, in-request**, every time a `ScheduledExpense`
is created or edited (`_generate_and_notify` in `budget/views/scheduled.py`).

Today, deduplication is based on `Expense.date_due` matching a computed
occurrence date. Two ways to break that:

1. A user hand-edits a generated expense's `date_due` (e.g. correcting the gym
   payment by one day). The next materialization pass no longer sees a match
   for the original occurrence and creates a duplicate.
2. A user edits the `ScheduledExpense`'s recurrence rule (`repeat_base_date`,
   `repeat_every_factor`/`unit`, `end_on`). Because materialization is
   synchronous on save, this duplicates every already-materialized future
   occurrence for the rest of the financial year **immediately**, not
   eventually.

This spec replaces date-based dedup with a stable occurrence identity, adds a
once-per-financial-year ratchet so the materializer stops silently re-running,
and locks the recurrence-defining fields behind an explicit, confirmed,
server-verified user action instead of allowing free-form edits to silently
reshape a year's worth of expenses.

Guiding principle (stated by the project owner): no partial reconciliation,
no per-instance prompting, no "smart" merge logic. Either nothing changes, or
the user was clearly told what's about to be wiped and confirmed it. Fewer
moving parts beats a cleverer algorithm.

---

## 1. Design decisions (confirmed)

| Topic | Decision |
|---|---|
| Occurrence identity | New immutable field `Expense.scheduled_occurrence_date`, set once at creation, never touched by expense edits |
| Duplicate prevention (normal path) | New field `ScheduledExpense.last_run` (financial-year int). Materializer skips a schedule entirely if `last_run == current_financial_year` for that schedule's owner |
| Re-run for a past year | Not possible through any UI/API path; `last_run` only advances forward |
| `--year` CLI override | Bypasses `last_run` entirely (admin/test tool); unaffected by this spec |
| Locked fields, group A | `repeat_every_factor` + `repeat_every_unit` — these redefine what "occurrence N" *means*, so any change invalidates every existing `scheduled_occurrence_date` on this schedule |
| Locked fields, group B | `repeat_base_date` + `end_on` — these only resize the occurrence *window*; existing occurrence identities stay meaningful |
| Group A change behavior | Requires "Modify schedule" checkbox + confirmation. On change: delete **every** materialized expense for this schedule in the current financial year — unconditionally, including already-settled/paid ones — then regenerate from scratch |
| Group B change behavior | Requires "Modify schedule time window" checkbox + confirmation. On change: force a regeneration pass (no full wipe); newly in-window occurrences are created, previously-materialized occurrences that are now outside the window are deleted — unconditionally, including already-settled ones |
| Client-side enforcement | Cosmetic only. Fields render disabled by default, showing their current value; checking the relevant checkbox requires an in-DOM confirm modal (reuse `window.confirmDialog`) before the fields unlock |
| Server-side enforcement | Authoritative. The view reads the transmitted checkbox flags directly from POST and independently decides whether to honor posted changes to locked fields, regardless of what the client's disabled state would suggest |
| No-op guard | Per gate: if the checkbox is checked but the posted values for that gate's fields equal the pre-edit values, nothing is wiped or regenerated |
| Auto-settle extra | When materializing an occurrence whose `date_due` is already `<= today` and `default_auto_settle_on_due_date` is true, create the expense with `settled=True` directly instead of relying on the separate `auto_settle_expenses` cron pass |
| Form layout | Move `default_auto_settle_on_due_date` down next to `deactivated` / `notify` in the create/edit form |
| REST API | **Open question, see §6** — not yet confirmed by the project owner |
| Deploy safety | `last_run` must be backfilled for all existing schedules at migration time (see §7); otherwise every schedule looks "never run this year" and the first post-deploy cron tick regenerates everyone's schedules simultaneously |

---

## 2. Data model changes

### `budget/models/expense.py`

```python
scheduled_occurrence_date = models.DateField(null=True, blank=True, default=None)
```

Set once, at creation, to the occurrence date computed by `occurrences_in_range`
for that materialized row. Never updated afterward — not by `expense_edit`,
not by the scheduled-update-instances wizard, not by anything. It is not shown
in any form; it exists purely as an internal dedup/identity key. `date_due`
keeps its current job (display, sorting, notifications, filters) unchanged.

### `budget/models/scheduled_expense.py`

```python
last_run = models.PositiveIntegerField(null=True, blank=True, default=None)
```

Financial-year label (as returned by `current_financial_month(...)[0]`) of the
most recent year this schedule was materialized for. `None` means never run.

Run `./venv/bin/python3 manage.py makemigrations` for both changes, then
`docker-compose exec web python manage.py migrate` to apply. See §7 for the
required data migration.

---

## 3. `generate_scheduled_expenses.py` — new algorithm

Per schedule (unless noted, this is the path used by both the cron and the
in-request calls):

1. Skip if `scheduled.deactivated`.
2. **Gate:** unless this run is forced (see §4) or invoked with `--year`, skip
   entirely if `scheduled.last_run == current_financial_month(feuser.month_start_day, feuser.month_start_prev)[0]`.
3. Compute `occurrences` = `occurrences_in_range(scheduled, start, end)`,
   filtered by `end_on`, exactly as today.
4. Fetch existing materialized rows scoped by **`scheduled_occurrence_date`**,
   not `date_due`:
   ```python
   existing = {
       e.scheduled_occurrence_date: e
       for e in Expense.objects.filter(
           source_scheduled=scheduled,
           scheduled_occurrence_date__gte=start,
           scheduled_occurrence_date__lte=end,
       )
   }
   ```
   (Filtering by `scheduled_occurrence_date` instead of `date_due` is what
   makes this immune to manual `date_due` edits on individual instances — the
   whole point of this spec.)
5. For each `occurrence` in `occurrences` not present in `existing`: create the
   expense exactly as today (`_generate_plain` / `_generate_with_assignment`),
   additionally setting `scheduled_occurrence_date=occurrence`, and applying
   the auto-settle extra: if `scheduled.default_auto_settle_on_due_date` and
   `occurrence <= today`, pass `settled=True` instead of `settled=False` into
   `create_expense(...)`.
6. **Prune:** for each entry in `existing` whose key is **not** in the
   freshly computed `occurrences` set, delete that `Expense` unconditionally
   (no settled/unsettled distinction). This step is inert in the ordinary
   yearly-rollover case (nothing is normally out of window) and only actually
   removes rows when a schedule's window was just narrowed (§4 Gate B).
7. If this run was not `--year`-overridden, set
   `scheduled.last_run = current_financial_year` and save.

This replaces the current `existing_dates` / per-occurrence date-matching
logic entirely — one dedup key (`scheduled_occurrence_date`), one pruning
step, no separate code paths for the two gates.

---

## 4. `views/scheduled.py` — `scheduled_edit`

### Reading intent

Before binding the form, snapshot the pre-edit locked values from `obj`:

```python
old_factor, old_unit = obj.repeat_every_factor, obj.repeat_every_unit
old_base, old_end = obj.repeat_base_date, obj.end_on
confirm_a = request.POST.get("confirm_modify_schedule") == "on"
confirm_b = request.POST.get("confirm_modify_schedule_window") == "on"
```

These two checkboxes are **not** model fields — read them straight off
`request.POST`, the same way `_parse_buddy_post` already handles the buddy
assignment fields separately from `ScheduledExpenseForm`.

### Server-side field lock (defense-in-depth)

Regardless of what the client's `disabled` attribute did or didn't submit,
before validating the form, force the locked fields back to their pre-edit
values in the POST data whenever their gate isn't confirmed:

```python
post_data = request.POST.copy()
if not confirm_a:
    post_data["repeat_every_factor"] = old_factor
    post_data["repeat_every_unit"] = old_unit
if not confirm_b:
    post_data["repeat_base_date"] = old_base
    post_data["end_on"] = old_end
form = ScheduledExpenseForm(post_data, instance=obj, feuser=feuser)
```

This is the actual security boundary. A tampered client that re-enables the
disabled inputs and submits new values without the checkbox gains nothing —
the server discards those values unconditionally.

### After `obj.save()`

```python
factor_unit_changed = (old_factor, old_unit) != (obj.repeat_every_factor, obj.repeat_every_unit)
window_changed = (old_base, old_end) != (obj.repeat_base_date, obj.end_on)

if confirm_a and factor_unit_changed:
    year = current_financial_month(feuser.month_start_day, feuser.month_start_prev)[0]
    start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
    Expense.objects.filter(
        source_scheduled=obj,
        scheduled_occurrence_date__gte=start,
        scheduled_occurrence_date__lte=end,
    ).delete()
    obj.last_run = None
    obj.save(update_fields=["last_run"])
elif confirm_b and window_changed:
    obj.last_run = None
    obj.save(update_fields=["last_run"])

_generate_and_notify(obj, feuser)  # unchanged call site
```

Resetting `last_run = None` before the existing `_generate_and_notify` call is
what forces this one schedule through the gate described in §3 step 2, while
every other schedule for this user in the same batch stays correctly gated.
No changes needed to the management command's CLI surface for this.

If neither gate fired (the common case — editing title, value, category,
etc.), `_generate_and_notify` still runs exactly as it does today, and now
simply no-ops via the `last_run` gate. No special-casing required.

### `scheduled_create`

Unaffected mechanically — creation has no "pre-edit value" to protect. After
the existing `_generate_and_notify` call succeeds, `last_run` is naturally set
to the current financial year by §3 step 7.

---

## 5. Template / JS changes — `budget/templates/budget/scheduled_form.html`

- `repeat_every_factor`, `repeat_every_unit`: disabled by default in edit mode
  (not in create mode), showing their current value.
- `repeat_base_date`, `end_on`: same, independently, disabled by default in
  edit mode.
- Two new checkboxes, unchecked by default, placed directly above their
  respective field group:
  - `id_confirm_modify_schedule` — label "Modify schedule"
  - `id_confirm_modify_schedule_window` — label "Modify schedule time window"
- Move `{{ form.default_auto_settle_on_due_date }}` down to sit alongside
  `{{ form.deactivated }}` / `{{ form.notify }}` (currently near line 73 vs.
  85/88 in the template).

### JS behavior (new, in the page's inline script or a small new file)

Reuse the existing global `window.confirmDialog(message, okLabel)` from
`templates/base.html` (already used for delete/confirm actions site-wide) —
do not build a bespoke modal.

On checking a gate's checkbox:
```js
confirmDialog(
  'Changing the schedule will delete and re-create ALL "<title>" expenses ' +
  'of <year>. All manual modifications are lost. Do you understand?',
  'Yes, continue'
).then(() => { /* enable group A fields */ })
 .catch(() => { checkbox.checked = false; });
```
Gate B's message: "Changing the schedule's time window may create additional
`<title>` expenses (if the window grows) or delete existing ones that now
fall outside it, including already-settled ones (if the window shrinks). Do
you understand?"

On unchecking a gate's checkbox (whether by direct click or via the cancel
path above): reset each field in that group to the value it held on page
load, then re-disable. Store original values in `data-original-value`
attributes at page load for this purpose.

**Submission gotcha:** native `disabled` inputs are excluded from form
submission entirely. If a field stays disabled, its value — including the
just-reset original value — never reaches the server, and the server-side
snapshot-and-restore logic in §4 has nothing to compare against for the
"unchanged" no-op guard. Fix: on form submit (capture the `submit` event
before the browser serializes it), temporarily set `disabled = false` on
*all* locked fields in both groups, regardless of checkbox state, so their
current values are always included in the POST body. The server remains the
sole authority on whether those values are honored.

---

## 6. Open question — REST API (`/api/v1/scheduled/<id>/` PATCH)

`tests/e2e/api/test_api.py::test_patch` currently PATCHes
`repeat_every_unit` directly via the Bearer-token API and expects it applied
immediately, with no confirmation concept at all. This spec does not resolve
whether Gate A/B protection should extend to the API.

**Recommendation (not yet confirmed):** apply the same protection, via two
boolean fields in the PATCH body (`confirm_modify_schedule`,
`confirm_modify_schedule_window`) mirroring the web form's checkboxes,
because the risk (silently reshaping a year of materialized expenses) is
identical regardless of which client makes the request — the checkbox is a
UI affordance for consent, not the actual safety mechanism, which lives
server-side and should be client-agnostic. If this recommendation is
accepted, `test_patch` needs updating to pass the confirm flag; if rejected,
document explicitly in code why the API is intentionally exempt.

**Do not implement §6 without an explicit decision from the project owner.**

---

## 7. Migration safety (required, not optional)

A plain `makemigrations`/`migrate` leaves every existing `ScheduledExpense.last_run`
as `NULL`. The very next `run_cron` tick after deploy would then see *every*
non-deactivated schedule in the system as "never run this year" and
regenerate + email-notify for all of them simultaneously — the exact kind of
mass event this spec exists to prevent.

Add a data migration that, for every non-deactivated `ScheduledExpense`,
computes `current_financial_month(owning_feuser.month_start_day,
owning_feuser.month_start_prev)[0]` and sets `last_run` to that value
directly (no regeneration, just backfilling the flag to reflect "this has
already effectively run for the current year," which is true for any schedule
that has been live under the old cron-driven system).

Also backfill `scheduled_occurrence_date` for existing generated expenses:
```
UPDATE budget_expense SET scheduled_occurrence_date = date_due
WHERE source_scheduled_id IS NOT NULL AND scheduled_occurrence_date IS NULL;
```
Caveat to document in the migration: this assumes `date_due` still reflects
the original occurrence for rows that predate this feature. Any row that was
already hand-edited before this migration ran cannot have its true original
occurrence recovered — this is a one-time, best-effort backfill, not a data
loss regression (those rows were already ambiguously identified before this
spec existed).

---

## 8. Test plan

### Unmodified (verified during spec research — no change needed)

`tests/unit/test_generate_scheduled_expenses.py` (pure `occurrences_in_range`
tests), `tests/e2e/scheduled/test_cron.py`, `test_deactivated.py`,
`test_scheduled_with_tags.py`, `test_scheduled_update_notifications.py`,
`test_scheduled_update_expenses.py`, `tests/e2e/projects/test_scheduled_assignment.py`
— repeat fields in these are only ever set at creation or re-posted unchanged
alongside other field updates (hits the no-op guard either way).

### Modify

- `tests/e2e/scheduled/test_scheduled.py::TestScheduledAllFields::test_all_fields_round_trip` —
  must check "Modify schedule" (and/or window) checkbox and pass its confirm
  dialog before it can fill/submit `repeat_every_factor`/`unit`/`repeat_base_date`.
- `tests/e2e/scheduled/test_scheduled.py::TestScheduledImmediateGeneration::test_edit_generates_new_expenses_immediately` —
  raw `requests.Session` POST that moves only `repeat_base_date` (pure Gate B
  case); must add `confirm_modify_schedule_window=on` to the POST body.
- `tests/e2e/api/test_api.py::test_patch` — depends on the §6 decision.

### New

- Regression test for the original bug: create scheduled expense → generate →
  hand-edit the generated expense's `date_due` → force a regeneration pass →
  still exactly one expense for that occurrence.
- `last_run` gate: second run within the same financial year is a true no-op;
  assert via `run_cmd` shell check on the field itself (not exposed over the
  API today).
- Gate A: (a) checkbox unchecked but tampered POST changes factor/unit → old
  values persist, nothing deleted; (b) checkbox checked + changed → all
  current-year expenses for the schedule deleted/regenerated, **including a
  pre-settled one**; (c) checkbox checked but unchanged → no-op (assert
  expense IDs unchanged, not just counts).
- Gate B: (a) shrinking the window deletes now-out-of-window expenses
  (including a settled one); (b) growing the window adds newly in-window
  occurrences without duplicating existing ones; (c) unchecked-but-tampered
  POST → old window wins.
- Auto-settle-on-create: schedule with `default_auto_settle_on_due_date=True`
  and a base date far enough in the past that some occurrences are already
  overdue at generation time → those are created `settled=True` directly.
- UI test: locked fields keep displaying their current value while disabled;
  unchecking a gate's checkbox reverts any in-progress edit back to the
  original value and re-disables.

### Delete

None — nothing in the current suite asserts behavior that becomes actively
wrong under this design.

---

## 9. Documentation

Per `CLAUDE.md`, keep `docs/src/` in sync. Check
`docs/src/docs/user-manual/` for any existing scheduled-expense page and
update it to describe: the once-per-year materialization, and that changing
the recurrence rule now requires an explicit confirmation because it
resets/deletes that year's generated expenses.
