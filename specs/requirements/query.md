# Query Language

Sources: `budget/query_parser.py`, `tests/unit/test_query_parser.py`,
docs `user-manual/dashboard/query-language.md`.

### Shared language
`req~query.shared~1`

The system shall use one query language for the expense list search, the project and buddy expense lists, the REST API `q` parameter and dashboard card queries.

Covers:
- `feat~query~1`

### Case insensitivity
`req~query.case~1`

The system shall evaluate all keys and values case-insensitively.

Covers:
- `feat~query~1`

### Free text
`req~query.free-text~1`

When a query contains a bare word or quoted phrase, the system shall match expenses whose title, payee or note, or the feuser's own overlay note, contains it, or whose participants, project or project members match it by first name, last name, email or offline display name.

Covers:
- `feat~query~1`

### Type filter
`req~query.type~1`

The system shall support `type=` with `expense`, `income`, `"savings deposit"` and `"savings withdrawal"`.

Covers:
- `feat~query~1`

### Boolean filters
`req~query.booleans~1`

The system shall support `settled=`, `deactivated=`, `recurring=` (generated from a recurring expense) and `shared=` (has at least one participant), each accepting yes/no, true/false and 1/0.

Covers:
- `feat~query~1`

### Participant filter
`req~query.participant~1`

The system shall support `participant=<text>` matching expenses whose owner or any participant matches the text in first name, last name, email or offline display name, and `participant=me` matching expenses the feuser owns or participates in.

Covers:
- `feat~query~1`

### Payer filter
`req~query.payer~1`

The system shall support `payer=<text>` matching the owning feuser, an offline upfront payer or an offline participant by name or email, and `payer=me` matching expenses the feuser paid.

Covers:
- `feat~query~1`

### Project filter
`req~query.project~1`

The system shall support `project=<text>` (project name contains text), `project=none` or `project=no` (no project) and `project=yes` (any project).

Covers:
- `feat~query~1`

### Category and tag filters
`req~query.cat-tag~1`

The system shall support `cat=<text>` and `tag=<text>` (title contains text) and `cat=none`, `tag=none` (none assigned), evaluated against the feuser's own category and tags for own expenses and against the feuser's own overlay for foreign expenses, never the foreign owner's classification.

Covers:
- `feat~query~1`

Tags: Privacy

### Payee filter
`req~query.payee~1`

The system shall support `payee=<text>` (contains) and `payee=none` (empty payee).

Covers:
- `feat~query~1`

### Value comparisons
`req~query.value~1`

The system shall support `value` with `=`, `==`, `<`, `<=`, `>` and `>=` against a number.

Covers:
- `feat~query~1`

### Date comparisons
`req~query.date~1`

The system shall support `date` comparisons against due dates written as `dd.mm.yyyy`, `mm/dd/yyyy` or `yyyy-mm-dd`, or the words `today`, `cur_week_start` (Monday) and `cur_week_end` (Sunday).

Covers:
- `feat~query~1`

### Logic
`req~query.logic~1`

The system shall combine space-separated terms with AND, support `||` for OR, `!` prefix for NOT and parentheses for grouping.

Covers:
- `feat~query~1`

### No raw SQL
`req~query.safe~1`

The system shall translate queries into ORM filter expressions only and never build SQL from query text.

Covers:
- `feat~query~1`

Tags: Security

### Visibility rule consistency
`req~query.visibility-consistency~1`

The own-or-overlay visibility rule for categories and tags shall give the same result in the query filters, the project tag chart, dashboard chart grouping in Shared mode, the Unclassified page and Sankey generation.

Comment:
Implemented in `_tag_q`/`_cat_q`, `visible_tag_titles`, `dashboard_cards._compute_chart`, `budget/unclassified.py` and `sankey_generation._resolve_node_q`.

Covers:
- `feat~query~1`
