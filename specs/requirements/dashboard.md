# Dashboards

Sources: former `docs/src/multiple-dashboards.md`, `budget/dashboard_cards.py`,
`budget/views/dashboard*.py`, `budget/dashboard_card_ai.py`, `budget/fixtures/`,
docs `user-manual/dashboard/`.

## Multiple dashboards

### Dashboard entry
`req~dashboard.entry~1`

When a feuser opens `/budget/`, the system shall redirect to their first dashboard (lowest sort order, ties by lowest ID).

Covers:
- `feat~dashboard~1`

### Dashboard ownership
`req~dashboard.ownership~1`

The system shall show, change or delete a dashboard or card only for its owner.

Covers:
- `feat~dashboard~1`

Tags: Security

### Tab bar
`req~dashboard.tabs~1`

The dashboard page shall show all of the feuser's dashboards as tabs in their sort order (a selector on mobile), with an add button creating a named dashboard and navigating to it.

Covers:
- `feat~dashboard~1`

Tags: UI

### Rename dashboard
`req~dashboard.rename~1`

When a feuser double-clicks a tab, the system shall let them rename the dashboard inline, saved on Enter or blur.

Covers:
- `feat~dashboard~1`

### Reorder dashboards
`req~dashboard.reorder~1`

When a feuser drags a tab to a new position, the system shall persist the new dashboard order.

Covers:
- `feat~dashboard~1`

### Delete dashboard
`req~dashboard.delete~1`

When a feuser deletes a dashboard after confirmation, the system shall delete it with its cards; if it is the feuser's last dashboard, then the system shall refuse the deletion.

Covers:
- `feat~dashboard~1`

### Move card
`req~dashboard.move-card~1`

The card editor shall offer "Move to dashboard" to move a card onto another of the feuser's dashboards.

Covers:
- `feat~dashboard~1`

## Cards

### Card storage
`req~dashboard.card.yaml~1`

The system shall store each card solely as a YAML document containing its type, configuration and layout.

Covers:
- `feat~dashboard~1`

### Card types
`req~dashboard.card.types~1`

The system shall support the card types `cell`, `bar-chart`, `pie-chart`, `list`, `line-chart`, `gauge` and `spacer`.

Covers:
- `feat~dashboard~1`

### Card validation
`req~dashboard.card.validation~1`

If a card's YAML is malformed, has an unknown type, unknown keys for its type or invalid values, then the system shall refuse to save it with a message naming the problem, and shall render an already stored invalid card as an error instead of failing the whole dashboard.

Covers:
- `feat~dashboard~1`

### Common fields
`req~dashboard.card.common~1`

Every non-spacer card shall have a required `title`, an optional `query` in the query language (default: all expenses in the period) and optional `flip_signs` multiplying the result by -1.

Covers:
- `feat~dashboard~1`

### Card scope
`req~dashboard.card.scope~1`

The system shall compute every card over the selected date range and Personal/Shared mode, excluding deactivated expenses, unless the card's query contains a date comparison.

Covers:
- `feat~dashboard~1`

### Methods
`req~dashboard.card.methods~1`

For cell, list and gauge cards the system shall support methods `sum` (all values positive), `total` (income and savings withdrawals negative) and `count`; bar and pie charts shall support `sum` and `total`.

Covers:
- `feat~dashboard~1`

### Layout
`req~dashboard.card.layout~1`

Each card shall have a desktop position, width (of 12 columns) and height (rows of about 90 px) and an optional independent mobile position, width (of 6 columns) and height; without mobile values the desktop values apply, capped at 6 columns.

Covers:
- `feat~dashboard~1`

### Drag and resize
`req~dashboard.card.drag-resize~1`

When a feuser drags a card by its header or resizes it with its corner handle, the system shall store the new order or size in the card's layout, for the desktop or mobile layout depending on the current screen width.

Covers:
- `feat~dashboard~1`

### Add and edit cards
`req~dashboard.card.editor~1`

The card editor shall let a feuser start from a built-in preset or write YAML directly, and save it as a new card at the end of the grid or as an update of an existing card.

Covers:
- `feat~dashboard~1`

### Delete card
`req~dashboard.card.delete~1`

When a feuser deletes a card after confirmation, the system shall remove it.

Covers:
- `feat~dashboard~1`

### Reset to defaults
`req~dashboard.card.reset~1`

The system shall offer "Reset dashboard" only on the feuser's first dashboard; after confirmation it shall replace that dashboard's cards with the default card set and leave other dashboards untouched.

Covers:
- `feat~dashboard~1`

### Presets and defaults
`req~dashboard.card.presets~1`

The system shall offer every predefined card as a preset, and give new users only the subset configured as default dashboards.

Covers:
- `feat~dashboard~1`

## Card types

### Cell card
`req~dashboard.type.cell~1`

A cell card shall show one computed number formatted by `template` (placeholders `$VALUE` with two decimals and `$CURRENCY_SYMBOL`, default "value currency"), with optional background and text colours per light and dark mode, optional `link` for the card body, and `color_breakpoints` where the last matching `less_than` threshold against the value selects the colours.

Covers:
- `feat~dashboard~1`

### Bar chart card
`req~dashboard.type.bar~1`

A bar chart card shall group by `categories` or `tags` (required), show one horizontal bar per group sorted descending, put expenses without a group under "Uncategorized", support `max_groups`, case-insensitive `hide_groups` and a `link_template` with `$GROUP_NAME` (`none` for Uncategorized).

Covers:
- `feat~dashboard~1`

### Pie chart card
`req~dashboard.type.pie~1`

A pie chart card shall group like a bar chart, with the legend below, a fixed palette of 15 colours repeated as needed, `hide_groups` and `link_template`.

Covers:
- `feat~dashboard~1`

### Chart amounts in Shared mode
`req~dashboard.type.shared-amounts~1`

While in Shared mode, chart grouping shall use the feuser's own category and tags or their overlay, and count foreign expenses at the feuser's share.

Covers:
- `feat~dashboard~1`

### List card
`req~dashboard.type.list~1`

A list card shall show matching expenses as rows of type abbreviation (EX, IN, SD, SW), title and rounded value, sorted by `order_by` (`date` default, `value`, `title`) and `order_dir` (`desc` default), tinted by type unless `type_colors: false`, with an optional summary row (`show_sum`, `method`, `flip_signs`, `sum_template`).

Covers:
- `feat~dashboard~1`

### Line chart card
`req~dashboard.type.line~1`

A line chart card shall plot one or more `series` (each with label, optional query combined with the card query, `sum` or `total` method, `flip_signs`, colour and `link_template` with `$START_DATE`/`$END_DATE`) over time buckets up to today, either cumulative (`cum`, default) or per bucket (`base`), drawn `smooth` (default) or `linear`, with optional soft (`suggested_min/max`) and hard (`limit_min/max`) y-axis bounds.

Covers:
- `feat~dashboard~1`

### Line chart buckets
`req~dashboard.type.line-buckets~1`

The system shall use one bucket per day for a date-range request and one bucket per 7 days for the legacy year view.

Covers:
- `feat~dashboard~1`

### Gauge card
`req~dashboard.type.gauge~1`

A gauge card shall require `query` and `method`, and exactly one of a positive fixed `max_value` or a `max_value_query` with `max_value_method`; it shall show an arc capped at full, optional raw values and percentage (both on by default, percentage may exceed 100), and colour breakpoints evaluated against the percentage of the maximum.

Covers:
- `feat~dashboard~1`

### Spacer card
`req~dashboard.type.spacer~1`

A spacer card shall accept only `type`, `positioning` and `hide_on` (`mobile` or `desktop`), occupy grid space invisibly, show an outline on hover, and be removed from the grid entirely on the screen size named in `hide_on`.

Covers:
- `feat~dashboard~1`

## AI card assist

### Generate card with AI
`req~dashboard.ai.generate~1`

Where AI is available to the feuser, the card editor shall offer to generate or modify the card YAML from a plain-language description and fill the editor with the result without saving it.

Covers:
- `feat~dashboard~1`

### AI card context
`req~dashboard.ai.context~1`

The card assist prompt shall be built from the current user manual pages on dashboard cards, the feuser's categories, tags and projects, and the YAML of their other cards.

Rationale:
Built from the docs at request time so the assistant stays in sync with the documented card schema.

Covers:
- `feat~dashboard~1`
