# Data Export

Sources: `comaney/csv_export.py`, `feusers/views/account.py`, `buddies/services/export.py`,
`budget/views/expenses.py`, docs `user-manual/data-export.md`.

### Expense list CSV
`req~export.list-csv~1`

When a feuser exports the expense list, the system shall download a CSV of exactly the expenses currently listed (range, mode and search applied) with the columns date due, title, type, value, payee, category, tags (pipe-separated), note and settled, named `expenses_<from>_to_<to>.csv`.

Covers:
- `feat~export~1`

### Account export
`req~export.account~1`

When a feuser requests the account export, the system shall download a ZIP of CSV files covering profile, all expenses, expense overlays, recurring templates, categories, tags, dashboards and cards, second factors (without secrets), Catalog Partnership membership, pending invitations and approvals, direct buddies with their shared expenses, participation and approvals, and the Sankey graph if saved.

Covers:
- `feat~export~1`

Tags: Privacy

### Masked AI settings in export
`req~export.ai-mask~1`

The account export shall show the active provider's secret AI settings as `********` plus the last 4 characters, and every value of other or undeclared fields fully masked.

Covers:
- `feat~export~1`

Tags: Security

### Project export
`req~export.project~1`

The system shall let project members export a project's metadata (including AI preprompt), members, expenses, participation matrix and approval matrices as CSV files.

Covers:
- `feat~export~1`

### Buddy summary export
`req~export.buddies~1`

The system shall let a feuser export their buddy data, including per direct buddy whether each side auto-accepts the other's entries (empty for offline buddies).

Covers:
- `feat~export~1`

### Formula injection protection
`req~export.formula-safe~1`

The system shall prefix every exported string cell that starts with a spreadsheet formula trigger with an apostrophe.

Rationale:
Exports contain text written by other users (buddies, partners).

Covers:
- `feat~export~1`

Tags: Security

### Undocumented exports
`req~export.silent~1`

The project, buddy and account CSV export details shall not be documented in the user manual beyond the account export and the expense list CSV.

Comment:
Owner decision.

Covers:
- `feat~export~1`
