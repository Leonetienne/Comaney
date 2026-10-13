# Unclassified Expenses

Sources: former `unclassified-expenses-spec.md`, `budget/unclassified.py`,
`budget/unclassified_ai.py`, `budget/views/unclassified.py`, `build/js/unclassified.js`,
docs `user-manual/unclassified-expenses.md`.

## Definition

### Own unclassified expense
`req~unclassified.def.own~1`

The system shall consider an expense owned by the feuser unclassified when it has no category or no tags.

Covers:
- `feat~unclassified~1`

### Foreign unclassified expense
`req~unclassified.def.foreign~1`

The system shall consider a foreign expense the feuser participates in unclassified when the feuser's own overlay for it is missing or has neither category nor tags, regardless of the owner's classification.

Covers:
- `feat~unclassified~1`

### Exclusions
`req~unclassified.def.exclusions~1`

The system shall never consider settlements, savings deposits or savings withdrawals unclassified; expenses in archived projects remain eligible.

Covers:
- `feat~unclassified~1`

### Problem label
`req~unclassified.def.problem~1`

The system shall label each unclassified expense "Category missing", "Tags missing" or "Category and Tags missing".

Covers:
- `feat~unclassified~1`

## Page

### Navigation badge
`req~unclassified.badge~1`

The sidebar entry "Unclassified Expenses" under Budget shall show a red count of the feuser's unclassified expenses whenever it is above zero.

Covers:
- `feat~unclassified~1`

Tags: UI

### List
`req~unclassified.list~1`

The page shall list all unclassified expenses newest first, unpaginated, with title, problem, category, tags and actions, and show an empty state when there are none.

Covers:
- `feat~unclassified~1`

### Provenance caption
`req~unclassified.provenance~1`

For a foreign expense, the row shall show a small caption "From <project>" or "From <owner>" under the title.

Covers:
- `feat~unclassified~1`

Tags: UI

### Inline category edit
`req~unclassified.edit.category~1`

When the feuser clicks a category cell, the row shall show a dropdown of the feuser's own categories.

Covers:
- `feat~unclassified~1`

### Inline tag edit
`req~unclassified.edit.tags~1`

When the feuser clicks a tags cell, the row shall show removable tag pills and a type-ahead offering only the feuser's own tags by case-insensitive substring match.

Covers:
- `feat~unclassified~1`

### Stable layout
`req~unclassified.edit.layout~1`

Entering edit mode shall not change column widths; widths change only through the column resize handles.

Covers:
- `feat~unclassified~1`

Tags: UI

### Dirty state
`req~unclassified.edit.dirty~1`

While a row has unsaved changes (manual or AI-suggested), it shall hide "Edit", show "Revert" and "Save", and highlight only the changed values.

Covers:
- `feat~unclassified~1`

Tags: UI

### Revert
`req~unclassified.edit.revert~1`

When the feuser clicks Revert, the row shall return to its last saved values.

Covers:
- `feat~unclassified~1`

### Save row
`req~unclassified.save.row~1`

When the feuser saves a row, the system shall write the category and tags to the expense if the feuser owns it, otherwise to the feuser's overlay (creating it if needed), and remove the row from the list once it is fully classified.

Covers:
- `feat~unclassified~1`

### Save validation
`req~unclassified.save.validation~1`

If a save names a category or tag outside the feuser's own catalog, or an expense the feuser neither owns nor participates in, then the system shall reject it.

Covers:
- `feat~unclassified~1`

Tags: Security

### Save all
`req~unclassified.save.all~1`

While at least one row is dirty, the page shall offer "Save all", which saves all dirty rows in one request.

Covers:
- `feat~unclassified~1`

### Edit link
`req~unclassified.edit-link~1`

The Edit action shall open the full expense editor for own expenses or the overlay editor for foreign expenses, returning to the Unclassified page after saving.

Covers:
- `feat~unclassified~1`

### Leave guard
`req~unclassified.leave-guard~1`

While any row is dirty, the page shall ask for browser confirmation before closing or reloading.

Covers:
- `feat~unclassified~1`

Tags: UI

## AI solving

### Let AI solve
`req~unclassified.ai.solve~1`

Where AI is available, when the feuser clicks "Let AI solve" on a row, the system shall block the page while waiting, then apply the suggestion as unsaved changes and relabel the button "Let AI retry".

Covers:
- `feat~unclassified~1`

### AI fills only missing fields
`req~unclassified.ai.missing-only~1`

The system shall apply an AI suggestion only to fields that were missing and only with entries from the feuser's own catalog, discarding anything else the AI returns.

Covers:
- `feat~unclassified~1`

### AI context
`req~unclassified.ai.context~1`

The AI request shall contain the feuser's custom instructions, their own category and tag catalog, the expense metadata and, for a foreign expense, the owner's category and tags as read-only hints.

Covers:
- `feat~unclassified~1`

Tags: Privacy

### AI cost display
`req~unclassified.ai.cost~1`

After each AI call the page shall briefly show the call's cost.

Covers:
- `feat~unclassified~1`

Tags: UI

### Let AI resolve all
`req~unclassified.ai.all~1`

When the feuser clicks "Let AI resolve all", the system shall request suggestions row by row for rows that are not dirty, showing a non-blocking progress panel with a running cost total and a Stop button that takes effect after the current request.

Covers:
- `feat~unclassified~1`

### AI unavailable mid-session
`req~unclassified.ai.unavailable~1`

If an AI call is refused because the feuser's AI budget is exhausted, then the page shall hide all AI buttons and keep existing pending changes.

Covers:
- `feat~unclassified~1`
