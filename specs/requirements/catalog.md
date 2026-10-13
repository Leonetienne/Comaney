# Categories and Tags

Sources: `budget/views/categories_tags.py`, `budget/models/category.py`, `budget/models/tag.py`,
docs `user-manual/categories-tags.md`.

### Per-feuser catalogs
`req~catalog.ownership~1`

The system shall keep a separate category list and tag list per feuser; no feuser can see or use another feuser's entries.

Covers:
- `feat~catalog~1`

Tags: Security

### One category, many tags
`req~catalog.cardinality~1`

The system shall allow at most one category and any number of tags per expense, recurring template and overlay.

Covers:
- `feat~catalog~1`

### Create
`req~catalog.create~1`

When a feuser creates a category or tag with a non-empty title of up to 128 characters, the system shall add it to their catalog.

Covers:
- `feat~catalog~1`

### Rename inline
`req~catalog.rename~1`

The Categories & Tags page shall let a feuser rename an entry inline (click the name, commit with Enter or blur).

Covers:
- `feat~catalog~1`

### Delete category
`req~catalog.delete-category~1`

When a feuser deletes a category, the system shall delete it and leave the expenses that used it uncategorised.

Covers:
- `feat~catalog~1`

### Delete tag
`req~catalog.delete-tag~1`

When a feuser deletes a tag, the system shall remove it from all expenses, templates and overlays that had it without deleting those records.

Covers:
- `feat~catalog~1`

### Partnership hints
`req~catalog.partnership-hints~1`

While a feuser is in a Catalog Partnership with completed onboarding, the Categories & Tags page shall show a banner that changes apply to all partners, and delete confirmations shall say the entry is deleted for all partners too.

Covers:
- `feat~catalog~1`

Tags: UI
