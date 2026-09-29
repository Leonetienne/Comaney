# Implementing Agent Onboarding: Custom Date Ranges

You are implementing the "Custom Date Ranges for Dashboards and Expense Lists" feature in
the Comaney Django application at `/Users/agent/private-work/Comaney/`.

**Your single source of truth is `date-range-spec.md`** in the project root. Read it first
and follow it precisely. The spec was written after a thorough review of the existing code
and reflects exact architectural decisions already confirmed by the project owner.

---

## What this feature does (in one paragraph)

The current year/month toggle navigation (with previous/next arrows) on the expense list and
dashboard is being **completely replaced** by a date range selector: preset buttons (current
financial month, previous/next financial months, current/prev/next year, Q1–Q4) plus two
calendar inputs (Start, End) and a Clear button. The selected range persists in
`localStorage` and is reflected in the URL. The same range applies to the personal expense
list, all dashboards, project expense lists, and the direct buddy expense list. D3 debt
graphs are never date-filtered (they show all-time data). Search-query date operators
(e.g. `date<2025-01-01`) override the global range and are applied instead of it.

---

## Key files to read before touching anything

Read these files to understand the current system:

- `budget/views/_period.py` — current period helpers (you will add to this)
- `budget/date_utils.py` — `financial_month_range`, `financial_year_range`, `current_financial_month`
- `budget/query_parser.py` — you will add `has_date_filter()` here
- `api/views/expenses.py` — you will add `date_from`/`date_to` support here
- `budget/views/dashboard_cards_api.py` — `_period_qs()` needs updating
- `budget/dashboard_cards.py` — `compute_card_data` needs to respect date override
- `buddies/views/projects.py` — you will add the charts-data endpoint and update the partial
- `buddies/views/main.py` — you will add the direct-expense partial endpoint
- `templates/partials/_month_nav.html` — the old nav you are replacing
- `budget/templates/budget/expenses_list.html` — uses Alpine.js / `window.EXPENSE_CONFIG`
- `budget/templates/budget/dashboard.html`
- `buddies/templates/buddies/project_detail.html` — charts + expense list (complex file)
- `buddies/templates/buddies/buddy_summary.html`
- `build/js/expenses.js` — Alpine.js component
- `build/js/dashboard.js`
- `tests/e2e/test_period.py` — delete this file
- `tests/unit/test_query_parser.py` — add unit tests here

---

## Critical rules (from CLAUDE.md)

- Never use em-dash. Use colon, semicolon, or rewrite.
- Never commit or push.
- New functional features or fixes must add tests.
- CSS: use CSS custom properties (`--var`) only. Never SCSS `$vars` (breaks dark mode).
- Auth: use `request.session["feuser_id"]` / `@feuser_required`. Never `request.user`.
- Always use `expense_factory.create_expense()` for new expenses; never `Expense()` directly.
- E2E tests: use `time.sleep()` then assert. Never `WebDriverWait.until()` after browser actions.
- E2E tests: use `execute_script` for inputs. Use XPath text match for buttons.
- Form submit selector: never use `form button[type=submit]`; scope to container.

---

## Implementation order

Work in this order to avoid breaking things mid-implementation:

1. **`budget/query_parser.py`**: Add `has_date_filter()`. Unit-test it.
2. **`budget/views/_period.py`**: Add `_date_range_presets_context(feuser)`.
3. **`build/js/date-range.js`**: Write the `dateRange` singleton.
4. **`build/scss/_date-range-nav.scss`** + import in `main.scss`.
5. **`templates/partials/_date_range_nav.html`**: New picker partial.
6. **Backend API changes**: `api/views/expenses.py`, `dashboard_cards_api.py`,
   `budget/dashboard_cards.py`, `budget/views/expenses.py` (export).
7. **Expense list page**: Update view + template + `expenses.js`.
8. **Dashboard page**: Update view + template + `dashboard.js`.
9. **New project charts endpoint**: `_compute_project_charts`, `project_charts_data` view,
   URL registration.
10. **Project detail page**: Template changes (AJAX charts, date range in expense list fetch,
    CSS class rename).
11. **`project_expense_list_partial`**: Add date range filtering.
12. **New buddy direct-expense partial endpoint**: `_compute_direct_expenses`,
    `direct_expense_list_partial` view, `direct_expense_partial.html` template, URL registration.
13. **Buddy summary page**: Template changes (AJAX expense list).
14. **Tests**: Delete `test_period.py`; write `test_date_range.py`; update `test_data_export.py`,
    `test_project_expense_filters.py`, and `test_sharing_mode.py` as needed.
15. **Documentation**: Update the three docs files listed in the spec.

---

## Test commands

Unit tests (run locally, no Docker):
```
venv/bin/pytest tests/unit/ -v
```

E2E tests (require live stack at :8080):
```
pytest -sx
```

Build assets (in Docker, never run npm directly):
```
build/build-assets.sh
```

---

## Things that must NOT be touched

- `_month_nav.html`: keep the file but it will no longer be included anywhere.
- `_period.py` existing helpers (`_get_month`, `_get_year`, `_get_period_mode`, etc.): keep
  them unchanged; the REST API still uses them for backward compat.
- The D3 debt graphs in `project_detail.html` and `buddy_summary.html`: all-time, server-rendered, untouched.
- The "Pay someone back" settlement form `<div class="add-buddy-panel">` in
  `project_detail.html` (line ~475): CSS class stays.
