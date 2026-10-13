# Expense Records

Sources: `budget/models/expense.py`, `budget/expense_factory.py`, `budget/views/expenses.py`,
`budget/services.py`, `templates/base.html`, docs `user-manual/expenses.md`,
`user-manual/buddies/shared-expenses.md`.

## Data

### Transaction types
`req~expenses.types~1`

The system shall support four transaction types: Expense, Income, Savings deposit and Savings withdrawal, where Expense and Savings deposit reduce the spending budget and Income and Savings withdrawal increase it.

Covers:
- `feat~expenses~1`

### Expense fields
`req~expenses.fields~1`

An expense shall have a required title (up to 128 characters), type and positive value (two decimals, up to 12 digits), and optional due date, payee (up to 128 characters), one category, any number of tags, note (up to 1024 characters), settled flag, auto-settle-on-due-date flag, notify flag and deactivated flag.

Covers:
- `feat~expenses~1`

### Positive values
`req~expenses.positive-value~1`

The system shall accept only positive values and derive the sign from the transaction type.

Covers:
- `feat~expenses~1`

### Own catalog only
`req~expenses.own-catalog~1`

The system shall let a feuser assign only categories and tags from their own catalog to their expenses.

Covers:
- `feat~expenses~1`

Tags: Security

### Shared expenses are spending
`req~expenses.shared-type~1`

If an expense assigned to a buddy or project has a type other than Expense, then the system shall reject it with 'Buddy and project expenses must be type "expense".'

Covers:
- `feat~expenses~1`

## Lifecycle

### Create expense
`req~expenses.create~1`

When a feuser saves the manual expense form, the system shall create the expense for them, optionally with a direct buddy or project assignment (see [sharing.md](sharing.md)).

Covers:
- `feat~expenses~1`

### Edit expense
`req~expenses.edit~1`

The system shall let a feuser edit their own expenses and, outside projects, expenses whose upfront payer is one of their offline buddies; inside a project only the admin may edit offline members' expenses.

Covers:
- `feat~expenses~1`

### Clone expense
`req~expenses.clone~1`

When a feuser clones an expense, the system shall create a copy with all details and the title prefixed with "CLONE - ".

Covers:
- `feat~expenses~1`

### Delete expense
`req~expenses.delete~1`

When the owner deletes an expense, the system shall remove it permanently, including all participants' shares.

Covers:
- `feat~expenses~1`

### Deactivate expense
`req~expenses.deactivate~1`

While an expense is deactivated, the system shall exclude it from all totals, charts and notifications but keep it in the history.

Covers:
- `feat~expenses~1`

### Settle manually
`req~expenses.settle~1`

When a feuser marks an unsettled expense as settled (form checkbox, bulk action or email link), the system shall set it settled and send the settled notification.

Covers:
- `feat~expenses~1`

### Auto-settle on due date
`req~expenses.auto-settle~1`

When the due date of an unsettled expense with auto-settle enabled has arrived, the system shall mark it settled during the next cron run.

Covers:
- `feat~expenses~1`

### Settlement edit lock
`req~expenses.settlement-lock~1`

If a settlement has been approved and confirmed by a real creditor other than its owner, then the system shall refuse to edit or delete it.

Covers:
- `feat~expenses~1`

## Expense list

### List scope
`req~expenses.list.scope~1`

The expense list shall show the feuser's expenses whose due date lies in the selected date range, in Personal or Shared mode (see [periods.md](periods.md)).

Covers:
- `feat~expenses~1`

### List search
`req~expenses.list.search~1`

The expense list shall filter by a query in the query language (see [query.md](query.md)); a query containing a date comparison shall override the selected date range.

Covers:
- `feat~expenses~1`

### List sorting and recurring filter
`req~expenses.list.sort~1`

The expense list shall sort by date (default, descending), title or value in either direction, and offer a "Hide recurring" checkbox equivalent to `recurring=no`.

Covers:
- `feat~expenses~1`

### Bulk actions
`req~expenses.list.bulk~1`

When a feuser selects expenses and chooses a bulk action, the system shall apply it to the selected own expenses: settle, unsettle, delete, add tag, remove tag or set category.

Covers:
- `feat~expenses~1`

### Selection total
`req~expenses.list.selection-total~1`

While expenses are selected, the list shall show the total value of the selection.

Covers:
- `feat~expenses~1`

Tags: UI

### Mute notifications per expense
`req~expenses.mute~1`

When a feuser mutes notifications for an expense (button or email link), the system shall clear its notify flag.

Covers:
- `feat~expenses~1`

## Overlay editor

### Overlay for foreign expenses
`req~expenses.overlay.edit~1`

When a participant edits a foreign expense, the system shall open a reduced editor that changes only their own category, tags and note for it, stored as an expense overlay without affecting the owner or other participants.

Covers:
- `feat~expenses~1`

### Overlay never empty
`req~expenses.overlay.no-empty~1`

The system shall never store an empty overlay; an overlay whose category, tags and note are all cleared shall be deleted.

Covers:
- `feat~expenses~1`

### Overlay auto-match category
`req~expenses.overlay.auto-category~1`

When a shared expense is created and a real participant has no overlay yet, the system shall pre-fill the participant's overlay category with their own category whose title equals the owner's category title.

Covers:
- `feat~expenses~1`

### Overlay auto-match tags
`req~expenses.overlay.auto-tags~1`

When a shared expense is created, the system shall pre-fill a participant's overlay tags by title match only if participant and owner are in the same Catalog Partnership with completed onboarding.

Rationale:
A coincidental title match between unrelated catalogs would silently hide the expense from the participant's Unclassified page.

Covers:
- `feat~expenses~1`

## Form helpers

### AI tag suggestion button
`req~expenses.form.ai-tags~1`

Where AI is available to the feuser, the expense and recurring expense forms shall offer "AI: select tags" (see [ai.md](ai.md)).

Covers:
- `feat~expenses~1`

### Date outside range warning
`req~expenses.form.range-warning~1`

When a feuser saves an expense whose date lies outside the currently selected date range, the system shall ask for confirmation before saving.

Covers:
- `feat~expenses~1`

Tags: UI

### Missing classification warning
`req~expenses.form.unclassified-warning~1`

While the save warning is enabled for the feuser, when they save an expense (manual form, recurring form or AI Express) that would be unclassified and they own at least one category (for a missing category) or tag (for missing tags), the system shall show one confirmation dialog offering to save anyway or "Don't show again".

Comment:
Settlements, savings deposits and savings withdrawals never trigger it.

Covers:
- `feat~expenses~1`

### Don't show again
`req~expenses.form.unclassified-dismiss~1`

When a non-demo feuser chooses "Don't show again", the system shall disable the missing classification warning for them; demo users shall not see this option.

Covers:
- `feat~expenses~1`

Tags: Demo

### Double submit guard
`req~expenses.form.double-submit~1`

When a form is submitted and the submit event is not cancelled, the system shall disable all its submit buttons until the page changes.

Covers:
- `feat~expenses~1`

Tags: UI
