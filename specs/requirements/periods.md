# Financial Periods and Date Ranges

Sources: former `date-range-spec.md`, `budget/date_utils.py`, `budget/views/_period.py`,
`build/js/date-range.js`, `budget/views/_sharing.py`, docs `user-manual/expenses.md`,
`user-manual/dashboard/index.md`.

## Financial periods

### Financial month
`req~periods.financial-month~1`

The system shall compute a financial month from the feuser's start day (1 to 31) and the "previous calendar month" flag; for example start day 27 with the flag set makes April run from 27 March to 26 April.

Covers:
- `feat~periods~1`

### Short months
`req~periods.short-months~1`

If the start day does not exist in a month, then the system shall use that month's last day as the start.

Covers:
- `feat~periods~1`

### Financial year
`req~periods.financial-year~1`

The system shall compute a financial year as the twelve financial months labelled with the same year.

Covers:
- `feat~periods~1`

### Year bounds
`req~periods.year-bounds~1`

If a request carries a year outside the supported range, then the system shall fall back to the current year instead of failing.

Covers:
- `feat~periods~1`

Tags: Security

## Date range picker

### Picker placement
`req~periods.picker.pages~1`

The date range picker shall appear on the expense list, dashboards, the Contact Expenses list and Sankey Studio; project pages always cover the project's entire history.

Covers:
- `feat~periods~1`

### Presets
`req~periods.picker.presets~1`

The picker shall offer presets for the previous, current and next financial month (labelled "Fin.<Month>"), the previous, current and next calendar year (1 Jan to 31 Dec), and calendar quarters Q1 to Q4 of the current year, each highlighted while the selected range matches it exactly.

Covers:
- `feat~periods~1`

### Custom range
`req~periods.picker.custom~1`

The picker shall offer Start and End date inputs that apply immediately on change; an end before the start shall not be accepted.

Covers:
- `feat~periods~1`

### Default range
`req~periods.picker.default~1`

The system shall use the current financial month as the default range on first visit and after "Clear".

Covers:
- `feat~periods~1`

### Range persistence
`req~periods.picker.persist~1`

The system shall remember the selected range in the browser across pages and reflect it in the URL as `date_from` and `date_to`; on load, valid URL parameters shall win over the stored range, which shall win over the default.

Covers:
- `feat~periods~1`

### Live refresh
`req~periods.picker.refresh~1`

When the range changes, every data component on the page shall reload for the new range without a full page reload.

Covers:
- `feat~periods~1`

### All-time debt views
`req~periods.picker.debts-all-time~1`

The system shall compute balances, debt graphs and settlement suggestions over all history, independent of the selected range.

Covers:
- `feat~periods~1`

### Query date override
`req~periods.query-override~1`

If a search or card query contains a date comparison (`date` followed by `==`, `<`, `<=`, `>` or `>=`), then the system shall ignore the selected range for that query.

Covers:
- `feat~periods~1`

## Personal and Shared mode

### Mode toggle
`req~periods.mode.toggle~1`

The expense list, dashboards and Sankey Studio shall offer a Personal/Shared toggle, remembered in the browser.

Covers:
- `feat~periods~1`

### Personal mode
`req~periods.mode.personal~1`

While in Personal mode, the system shall count only the feuser's own expenses, at full value.

Covers:
- `feat~periods~1`

### Shared mode
`req~periods.mode.shared~1`

While in Shared mode, the system shall count the feuser's own expenses and the foreign expenses they participate in, each at the feuser's own share.

Covers:
- `feat~periods~1`
