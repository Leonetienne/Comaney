# Recurring Expenses

Sources: former `scheduled-integrity-spec.md`, `budget/models/scheduled_expense.py`,
`budget/views/scheduled.py`, `budget/management/commands/generate_scheduled_expenses.py`,
`budget/scheduled_assignment.py`, docs `user-manual/scheduled-expenses.md`, `api-access.md`.

## Templates

### Template fields
`req~scheduled.fields~1`

A recurring expense template shall have the expense fields (title, type, value, payee, category, tags, note, notify, default auto-settle) plus repeat base date, repeat factor (positive integer), repeat unit (days, weeks, months, years), optional end date and a deactivated flag.

Covers:
- `feat~scheduled~1`

### Template assignment
`req~scheduled.assignment~1`

A template shall optionally carry a contact or project assignment with upfront payer and participant shares, applied to every expense generated from it.

Covers:
- `feat~scheduled~1`

### Template list
`req~scheduled.list~1`

The recurring expense list shall show all templates regardless of period, with their next due date and repeat schedule.

Covers:
- `feat~scheduled~1`

### Clone template
`req~scheduled.clone~1`

When a feuser clones a template, the system shall create a copy with the title prefixed with "CLONE - ".

Covers:
- `feat~scheduled~1`

### Delete template
`req~scheduled.delete~1`

When a feuser deletes a template, the system shall delete the template and keep the already generated expenses as ordinary expenses.

Covers:
- `feat~scheduled~1`

### Deactivate template
`req~scheduled.deactivate~1`

While a template is deactivated, the system shall generate no expenses from it and leave existing ones untouched.

Covers:
- `feat~scheduled~1`

## Materialisation

### Occurrence computation
`req~scheduled.occurrences~1`

The system shall compute occurrences as the repeat base date plus whole multiples of the repeat interval, limited to the current financial year of the owner and to dates on or before the end date if set.

Covers:
- `feat~scheduled~1`

### Generation triggers
`req~scheduled.triggers~1`

The system shall materialise occurrences into expenses on every cron run and synchronously when a template is created or edited.

Covers:
- `feat~scheduled~1`

### Whole year including past dates
`req~scheduled.whole-year~1`

When a template is materialised, the system shall create expenses for all its occurrences in the current financial year, including dates in the past.

Covers:
- `feat~scheduled~1`

### Occurrence identity
`req~scheduled.occurrence-identity~1`

The system shall stamp every generated expense with an immutable occurrence date, never shown or editable, and use it as the only deduplication key, so editing a generated expense's due date never causes a duplicate.

Covers:
- `feat~scheduled~1`

### Once per financial year
`req~scheduled.once-per-year~1`

The system shall materialise each template at most once per financial year of its owner, recorded in `last_run`; later runs in the same year shall do nothing for it.

Rationale:
Stops repeated silent regeneration of expenses the user may have edited or deleted.

Covers:
- `feat~scheduled~1`

### Admin year override
`req~scheduled.year-override~1`

Where `generate_scheduled_expenses` is run with `--year`, the system shall bypass the once-per-year gate and not update `last_run`.

Covers:
- `feat~scheduled~1`

Tags: Operations

### Overdue occurrences auto-settled
`req~scheduled.auto-settle-past~1`

When an occurrence dated today or earlier is generated from a template with default auto-settle enabled, the system shall create it already settled.

Covers:
- `feat~scheduled~1`

### Participant notification on generation
`req~scheduled.notify-participants~1`

When generation triggered by a template create or edit creates shared expenses, the system shall notify their participants the same way as for manually created shared expenses.

Covers:
- `feat~scheduled~1`

## Editing the schedule

### Locked repeat fields
`req~scheduled.edit.locked~1`

When editing an existing template, the form shall show repeat factor and unit (gate A) and repeat base date and end date (gate B) disabled with their current values, each group unlocked only by its own checkbox, "Modify schedule" or "Modify schedule time window", after a confirmation dialog.

Covers:
- `feat~scheduled~1`

Tags: UI

### Revert on uncheck
`req~scheduled.edit.revert~1`

When a gate checkbox is unchecked, the form shall restore that group's original values and disable the fields again.

Covers:
- `feat~scheduled~1`

Tags: UI

### Server-side lock
`req~scheduled.edit.server-lock~1`

If a template update changes gate A or gate B fields without the matching confirmation flag, then the system shall discard those field changes and still apply all other changes; this shall hold for the web form and the REST API alike.

Covers:
- `feat~scheduled~1`

Tags: Security

### Gate A regeneration
`req~scheduled.edit.gate-a~1`

When a confirmed edit changes the repeat factor or unit, the system shall delete every expense generated from the template in the current financial year, settled ones included, and regenerate from scratch.

Covers:
- `feat~scheduled~1`

### Gate B regeneration
`req~scheduled.edit.gate-b~1`

When a confirmed edit changes the base date or end date, the system shall delete generated current-year expenses whose occurrence now falls outside the window, settled ones included, add newly in-window occurrences and leave the others untouched.

Covers:
- `feat~scheduled~1`

### No-op gate
`req~scheduled.edit.no-op~1`

If a gate is confirmed but its fields are unchanged, then the system shall delete and regenerate nothing.

Covers:
- `feat~scheduled~1`

### Template changes do not rewrite history
`req~scheduled.edit.history~1`

When a template's other fields change, the system shall leave already generated expenses unchanged.

Covers:
- `feat~scheduled~1`

## Updating generated expenses

### Update expenses dialog
`req~scheduled.update.dialog~1`

The template page shall offer "Update expenses", listing the template's generated expenses of the current financial year, all preselected, with Select all, Deselect all and Select unsettled.

Covers:
- `feat~scheduled~1`

### Apply template to selected
`req~scheduled.update.apply~1`

When the feuser confirms, the system shall copy the template's title, payee, note, category, tags, type, value, auto-settle, notify and assignment onto the selected expenses, and notify affected participants of the changes.

Covers:
- `feat~scheduled~1`

## Roster changes

### Assignment upkeep
`req~scheduled.roster~1`

When a referenced contact or offline member is removed, merged or replaced, the system shall update or clear every template assignment referencing them so no template references a missing participant.

Covers:
- `feat~scheduled~1`
