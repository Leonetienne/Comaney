# Spec: Custom Date Ranges for Dashboards and Expense Lists

## Summary

Replace the current month/year toggle navigation with a date range selector. Users pick
a start and end date via two calendar inputs plus preset buttons. The selection persists
in `localStorage` and is reflected in the URL. It affects personal expenses, dashboards,
project expense lists, and direct buddy expense lists. Debt graphs (D3) remain all-time.
Search-query date operators override the global range.

---

## 1. Design decisions (confirmed)

| Topic | Decision |
|---|---|
| State storage | `localStorage` (key `comaney_date_range`) |
| URL reflection | Yes — `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`; URL takes precedence over localStorage on load |
| Quarters | Calendar-based (Q1 = Jan–Mar, Q2 = Apr–Jun, Q3 = Jul–Sep, Q4 = Oct–Dec) |
| Project charts | New AJAX endpoint; charts re-render without page reload |
| Date override in queries | `has_date_filter()` added to `query_parser.py`; views skip period filter when it returns True |
| API backward compat | `date_from`/`date_to` take precedence; `year`/`month`/`view` still work |
| Direct buddy expenses | AJAX-driven partial (new endpoint), with search + sort + date range |
| Export filename | `expenses_YYYY-MM-DD_to_YYYY-MM-DD.csv` |
| Documentation | Update `docs/src/docs/user-manual/expenses.md`, `projects.md`, and `api-access.md` |

---

## 2. Presets

Presets are computed server-side on every page load from the user's `month_start_day` and
`month_start_prev` settings. The server injects them as JSON into the page.

| Key | Label format | Range |
|---|---|---|
| `cur_fin_month` | `Fin.June` | Current financial month start/end |
| `prev_fin_month` | `Fin.May` | Previous financial month start/end |
| `next_fin_month` | `Fin.July` | Next financial month start/end |
| `cur_year` | `2026` | `financial_year_range(current_calendar_year, ...)` |
| `prev_year` | `2025` | Financial year for previous calendar year |
| `next_year` | `2027` | Financial year for next calendar year |
| `q1` | `Q1` | Jan 1 to Mar 31 of current calendar year |
| `q2` | `Q2` | Apr 1 to Jun 30 of current calendar year |
| `q3` | `Q3` | Jul 1 to Sep 30 of current calendar year |
| `q4` | `Q4` | Oct 1 to Dec 31 of current calendar year |

**Default (on first visit / after Clear):** `cur_fin_month`.

### Server helper: `_date_range_presets_context(feuser)`

Add to `budget/views/_period.py`. Returns a dict with:

```python
{
    "date_range_presets_json": "<mark_safe JSON string>",
    "date_range_default_from": "YYYY-MM-DD",  # cur_fin_month start
    "date_range_default_to":   "YYYY-MM-DD",  # cur_fin_month end
}
```

Each preset entry in the JSON:
```json
{
  "cur_fin_month":  {"label": "Fin.June", "from": "2026-06-01", "to": "2026-06-30"},
  "prev_fin_month": {"label": "Fin.May",  "from": "2026-05-01", "to": "2026-05-31"},
  "next_fin_month": {"label": "Fin.July", "from": "2026-07-01", "to": "2026-07-31"},
  "cur_year":       {"label": "2026",     "from": "2026-01-01", "to": "2026-12-31"},
  "prev_year":      {"label": "2025",     "from": "2025-01-01", "to": "2025-12-31"},
  "next_year":      {"label": "2027",     "from": "2027-01-01", "to": "2027-12-31"},
  "q1": {"label": "Q1", "from": "2026-01-01", "to": "2026-03-31"},
  "q2": {"label": "Q2", "from": "2026-04-01", "to": "2026-06-30"},
  "q3": {"label": "Q3", "from": "2026-07-01", "to": "2026-09-30"},
  "q4": {"label": "Q4", "from": "2026-10-01", "to": "2026-12-31"}
}
```

The "cur/prev/next year" presets use `financial_year_range(year, feuser.month_start_day,
feuser.month_start_prev)` so they align with the user's financial year (not necessarily
Jan 1 to Dec 31). The label is always just the calendar year number (e.g. "2026").

Quarters always use fixed calendar dates regardless of `month_start_day`.

---

## 3. State management (client-side)

A new file `build/js/date-range.js` exports a `dateRange` singleton. It is bundled by
esbuild into the entry points that need it (`expenses.js`, `dashboard.js`, and any page
that hosts the date range picker).

### Priority on page load (highest first)

1. URL params `date_from` + `date_to` — if both present and valid ISO dates (`YYYY-MM-DD`),
   use them and write them to `localStorage` as the new stored value.
2. `localStorage` key `comaney_date_range` — stores `{from: "YYYY-MM-DD", to: "YYYY-MM-DD"}`.
3. Server-injected default — `window.DATE_RANGE_CONFIG.defaultFrom` /
   `window.DATE_RANGE_CONFIG.defaultTo` (the current financial month computed at page load).

### dateRange API

```js
dateRange.get()    // Returns {from: "YYYY-MM-DD", to: "YYYY-MM-DD"}
dateRange.set(from, to)  // Saves to localStorage; updates URL; fires "daterangechange"
dateRange.clear()  // Resets to server default (window.DATE_RANGE_CONFIG.defaultFrom/To)
```

`dateRange.set()` calls `history.replaceState` to update `?date_from=...&date_to=...` in
the URL without a page reload. All other existing URL params are preserved.

`dateRange.set()` dispatches `new CustomEvent("daterangechange", {detail: {from, to}})` on
`window`. Every data-fetching component listens for this event to re-fetch.

---

## 4. Date range picker widget (UI)

### New partial: `templates/partials/_date_range_nav.html`

This partial replaces `_month_nav.html` on all pages. It receives these context variables
(all provided by `_date_range_presets_context()` merged into the view context):
- `date_range_presets_json` — JSON string for `window.DATE_RANGE_CONFIG.presets`
- `date_range_default_from` / `date_range_default_to` — strings
- `nav_show_sharing_toggle` — bool (only on expense list and dashboard)
- `initial_date_from` / `initial_date_to` — from URL params if present on page load (empty string if absent)

### Visual layout

```
[ Fin.June ] [ Fin.May ] [ Fin.July ] [ 2026 ] [ 2025 ] [ 2027 ] [ Q1 ] [ Q2 ] [ Q3 ] [ Q4 ]  [Clear]
Start [____-__-__]   End [____-__-__]
```

The preset order in the UI matches the table in §2 (financial months first, then years,
then quarters). Preset buttons wrap on narrow screens.

The active preset (if any) gets an "active" CSS class. Comparison: if current `{from, to}`
exactly matches a preset's `{from, to}`, highlight that preset.

Changing either date input immediately calls `dateRange.set()`.

The sharing toggle (`Personal / Shared`) lives inside the same nav component but is
rendered only when `nav_show_sharing_toggle` is true. Wrap it in `{% if nav_show_sharing_toggle %}`.

### SCSS: `build/scss/_date-range-nav.scss`

New file. Import it in `build/scss/main.scss`. Use CSS custom properties (`--var`) only,
never SCSS `$vars` (see CLAUDE.md rule). Structure it similarly to `_month-nav.scss`.

---

## 5. Pages affected and what changes

### 5.1 Personal expense list (`/budget/expenses/`)

**View `expenses_list` in `budget/views/expenses.py`:**
- Remove calls to `_get_period_mode`, `_get_month`, `_get_year`, `_month_nav_context`,
  `_year_nav_context`.
- Call `_date_range_presets_context(feuser)` and merge into context.
- Read `initial_date_from = request.GET.get("date_from", "")` and
  `initial_date_to = request.GET.get("date_to", "")` and add to context.
- Keep `nav_show_sharing_toggle` in context (unchanged).

**Template `budget/templates/budget/expenses_list.html`:**
- Replace `{% include "partials/_month_nav.html" %}` with
  `{% include "partials/_date_range_nav.html" %}`.
- Remove year/month/mode from `window.EXPENSE_CONFIG`; add `dateFrom`, `dateTo`
  (populated from initial URL params or empty, JS takes over from there).

**`build/js/expenses.js`:**
- Import `dateRange` from `./date-range.js`.
- Remove `periodYear`, `periodMonth`, `periodMode` properties.
- Add `dateFrom`, `dateTo` initialized from `dateRange.get()`.
- In `init()`: initialize from `dateRange.get()`; add event listener for `"daterangechange"`.
- `fetchExpenses()`: send `date_from`/`date_to` instead of `year`/`month`/`view`.
- `exportHref`: use `?date_from=...&date_to=...`.

### 5.2 Dashboard (`/budget/dash/<uid>/`)

**View `dashboard_detail` in `budget/views/dashboard.py`:**
- Same changes as 5.1 view: remove period helpers, call `_date_range_presets_context`.

**Template `budget/templates/budget/dashboard.html`:**
- Replace `_month_nav.html` with `_date_range_nav.html`.
- Remove year/month/mode from JS config; add date range.

**`build/js/dashboard.js`:**
- Import `dateRange`; swap period params for `date_from`/`date_to` in the cards data fetch.
- Listen for `"daterangechange"` to re-fetch cards.

### 5.3 Project detail (`/projects/<id>/`)

**View `project_detail` in `buddies/views/projects.py`:**
- Call `_date_range_presets_context(feuser)` and merge into context.
- Extract chart computation into `_compute_project_charts(feuser, project, start_date, end_date)`.
  This function contains the current code for `spending_pie_json`, `spending_over_time_json`,
  and `tag_dist_json`.
- Remove those three computed values from the context; replace with `None` or drop them.
  The D3 variables `raw_graph_json`, `simplified_graph_json`, `raw_debts_json`,
  `settle_all_pairs_json` are **NOT** date-filtered and remain server-rendered as today.
- Keep `group_total_spending` out of context too (it will come from the AJAX response);
  or keep it as an all-time value and re-label in the template.

**Template `buddies/templates/buddies/project_detail.html`:**
- Add `{% include "partials/_date_range_nav.html" %}` near the top (after the project
  hero section, before the balances section).
- Remove inline `PIE_DATA`, spending-over-time, and tag-dist script/data blocks.
  Replace each chart section's content div with a loading-state placeholder:
  `<div id="group-spending-pie" class="group-spending-chart" data-loading></div>`
- Add a script block at the end that:
  - On load: reads `dateRange.get()`, fetches charts from `{% url 'projects:project_charts_data' project_id=project.uid %}?date_from=...&date_to=...`
  - On `"daterangechange"`: re-fetches and re-renders using the same D3/rendering functions
    that are already defined earlier in the template (keep them — just remove their initial
    call and the inline data that fed them).
- Add `date_from`/`date_to` to the existing `fetchList()` params (line ~641 in current file).
- Rename `class="add-buddy-panel"` to `class="exp-filter-panel"` on the expense filter
  section (line ~582). The settlement section at line ~475 also uses `add-buddy-panel`
  — that one stays.

### 5.4 Buddy summary (`/buddies/summary/`)

**View `buddy_summary_page` in `buddies/views/main.py`:**
- Call `_date_range_presets_context(feuser)` and merge into context.
- Remove `direct_expense_data` computation from this view; the partial endpoint handles it.
- Keep everything else (debts, pending approvals, settlement members).

**Template `buddies/templates/buddies/buddy_summary.html`:**
- Add `{% include "partials/_date_range_nav.html" %}` near the top.
- Replace the `{% if direct_expense_data %}...{% endfor %}` block with:
  ```html
  <div id="buddy-direct-exp-container"
       data-partial-url="{% url 'buddies:direct_expense_list_partial' %}">
  </div>
  ```
- Add a script block that fetches the partial on load and on `"daterangechange"` (same
  pattern as the project expense list).

---

## 6. New AJAX endpoints

### 6.1 Project charts data

```
GET /projects/<project_id>/charts-data/
    ?date_from=YYYY-MM-DD
    &date_to=YYYY-MM-DD
```

**View:** `project_charts_data` in `buddies/views/projects.py`

Decorator: `@feuser_required`

User must be a project member (`get_object_or_404(..., members__feuser=feuser)`).

**Logic:**
- Parse `date_from`, `date_to`. On missing or invalid: use all-time (no filter).
- Call `_compute_project_charts(feuser, project, start_date, end_date)`.
- Return `JsonResponse`.

**Response JSON:**
```json
{
  "spending_pie": [...],
  "spending_over_time": null,
  "tag_dist": null,
  "group_total_spending": "123.45"
}
```

The exact shapes mirror the current `spending_pie_json`, `spending_over_time_json`,
`tag_dist_json` template variables. `null` is returned when there is insufficient data
(as the current code already handles).

**`_compute_project_charts(feuser, project, start_date, end_date)`:**
- Takes the full breakdown from `BuddyQueryService.get_group_full_breakdown(feuser, project)`.
- Filters `approved_expenses` to those where `expense.date_due` (or `expense.date_created.date()`
  as fallback) falls in `[start_date, end_date]`. If `start_date` or `end_date` is None,
  no date filter is applied.
- Then runs the same pie/line/tag-dist aggregation that currently lives in `project_detail()`.

**URL in `buddies/urls_projects.py`:**
```python
path("<int:project_id>/charts-data/", views.project_charts_data, name="project_charts_data"),
```

### 6.2 Direct buddy expense list partial

```
GET /buddies/direct-expenses/partial/
    ?date_from=YYYY-MM-DD
    &date_to=YYYY-MM-DD
    &q=<search string>
    &sort_by=date|title|value
    &sort_dir=desc|asc
```

**View:** `direct_expense_list_partial` in `buddies/views/main.py`

Decorator: `@feuser_required`

**`_compute_direct_expenses(feuser, start, end, q, sort_by, sort_dir)`:**
Extract from `buddy_summary_page`: the `direct_expenses_qs` build, overlay notes fetch, and
`direct_expense_data` list construction.
Add date filter: filter the queryset by `date_due__gte=start, date_due__lte=end` if `start`
and `end` are provided, UNLESS `has_date_filter(q)` is True (query overrides range).
Apply `apply_query(qs, q, feuser=feuser)` for search.
Apply sorting: same sort map as project list (`date`, `title`, `value`).

**Template:** `buddies/templates/buddies/direct_expense_partial.html` (new).
Renders:
- Search + sort controls (`.exp-controls`, `.exp-toolbar`) — same structure as
  `project_detail.html` expense controls but with IDs `buddy-exp-search`,
  `buddy-exp-sort-by`, `buddy-exp-sort-dir`. No `i_paid` or `hide_recurring` checkboxes
  (those are project-specific).
- The expense card list using the same markup as the current `direct_expense_data` loop
  in `buddy_summary.html`.
- An "Advanced search filters" link (same as project expense list).
- A "no results" message when the list is empty.

**URL in `buddies/urls.py`:**
```python
path("direct-expenses/partial/", views.direct_expense_list_partial, name="direct_expense_list_partial"),
```

---

## 7. Backend: date range in existing endpoints

### 7.1 `api/views/expenses.py`

In the `GET` handler, resolve the date range:
```python
from budget.query_parser import has_date_filter

date_from_raw = request.GET.get("date_from")
date_to_raw   = request.GET.get("date_to")
q_str = request.GET.get("q", "")

if date_from_raw and date_to_raw:
    try:
        start = date.fromisoformat(date_from_raw)
        end   = date.fromisoformat(date_to_raw)
    except ValueError:
        return _err("Invalid date_from or date_to.")
else:
    year, month = _parse_month(request, feuser)
    view = request.GET.get("view")
    if view == "year":
        start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
    else:
        start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)

# Skip period filter if the query itself contains date operators
if has_date_filter(q_str):
    # Build qs without date range
    qs = Expense.objects.filter(owning_feuser=feuser, is_dummy=False)
else:
    qs = Expense.objects.filter(owning_feuser=feuser, date_due__gte=start, date_due__lte=end, is_dummy=False)
```

### 7.2 `budget/views/dashboard_cards_api.py`

In `_period_qs()`, add the same `date_from`/`date_to` precedence:
```python
date_from_raw = request.GET.get("date_from")
date_to_raw   = request.GET.get("date_to")
if date_from_raw and date_to_raw:
    try:
        start = date.fromisoformat(date_from_raw)
        end   = date.fromisoformat(date_to_raw)
    except ValueError:
        pass  # fall through to year/month
else:
    # existing _get_period_mode / _get_year / _get_month logic
```

For cards whose `query` field contains date operators: `compute_card_data` in
`budget/dashboard_cards.py` receives the period queryset. Check
`has_date_filter(config.get("query", ""))` in `compute_card_data`; if True, replace the
passed queryset with an unfiltered one (all expenses, no date range) before applying
`apply_query`. This allows cards like `query: "date>=2025-01-01"` to work regardless of
the UI date range.

### 7.3 `budget/views/expenses.py` — export

`expenses_export` view:
```python
date_from_raw = request.GET.get("date_from")
date_to_raw   = request.GET.get("date_to")
if date_from_raw and date_to_raw:
    try:
        start = date.fromisoformat(date_from_raw)
        end   = date.fromisoformat(date_to_raw)
        label = f"{start.isoformat()}_to_{end.isoformat()}"
    except ValueError:
        # fall through to old logic
        date_from_raw = None
if not date_from_raw:
    # existing year/month/view logic
    ...
    label = ...  # existing label format
```

### 7.4 `buddies/views/projects.py` — partial date filtering

`project_expense_list_partial`:
- Parse `date_from`, `date_to`.
- After building `matching_pks` from `apply_query`, additionally filter by date range:
  ```python
  if date_from and date_to and not has_date_filter(effective_q):
      date_pks = set(
          Expense.objects.filter(
              project=project,
              date_due__gte=date_from,
              date_due__lte=date_to,
          ).values_list("pk", flat=True)
      )
      matching_pks = (matching_pks & date_pks) if matching_pks is not None else date_pks
  ```
  Note: this operates on PKs so it composes cleanly with the existing query filter logic.

---

## 8. `budget/query_parser.py` — `has_date_filter`

Add this function (no Django dependency):

```python
import re as _re

def has_date_filter(query_str: str) -> bool:
    """Return True if the query contains any date comparison operator."""
    return bool(_re.search(r'\bdate\s*(?:==|[<>]=?)', query_str or ''))
```

---

## 9. CSS class name fix

In `buddies/templates/buddies/project_detail.html`:
- The expense filter controls section (currently line ~582) has `class="add-buddy-panel"`.
  Change it to `class="exp-filter-panel"` with `style="margin-bottom:1.25rem;"` preserved.
- The "Pay someone back" settlement section (line ~475) also uses `class="add-buddy-panel"`.
  That one is semantically correct; leave it unchanged.

If `tests/e2e/buddies/test_project_expense_filters.py` selects by `.add-buddy-panel`,
update those selectors to `.exp-filter-panel`.

---

## 10. Backward compatibility

- All existing `?year=&month=&view=year` URL patterns continue to work in the API.
- `_parse_month()`, `_get_month()`, `_get_year()`, and `_period.py` period helpers are
  unchanged and kept for the API's use.
- Old expense list bookmarks (`/budget/expenses/?year=2026&month=6`) still load the page;
  the date range picker ignores those old params (they are not `date_from`/`date_to`) and
  falls back to localStorage or the default. This is acceptable: the period UI no longer
  uses those params.
- The `expenses_export` view accepts both old and new params.

---

## 11. Tests

### 11.1 Delete

`tests/e2e/test_period.py` — tests the removed month/year toggle UI. **Delete this file.**

### 11.2 New `tests/e2e/test_date_range.py`

All Selenium E2E tests. Follow the conventions in the existing test files:
- Use `setup_user` / `cleanup_user` from `helpers`.
- Use `time.sleep()`, NOT `WebDriverWait.until()`, after browser actions.
- Use `execute_script` for inputs, XPath text match for buttons.

**Test cases:**

| Test name | What it verifies |
|---|---|
| `test_default_shows_current_fin_month` | Default date range equals current fin month dates |
| `test_preset_q1_filters_expenses` | Jan expense visible in Q1, invisible in Q2 |
| `test_preset_cur_year` | Year preset covers all 12 fin months |
| `test_custom_date_input` | Typing start/end dates shows correct expenses |
| `test_clear_resets_to_default` | After selecting Q4 then Clear, default restored |
| `test_range_persists_to_dashboard` | Set Q2 on expense list, navigate to dashboard, picker shows Q2 |
| `test_url_reflects_range` | After selecting Q1, URL contains `date_from=YYYY-01-01&date_to=YYYY-03-31` |
| `test_url_param_sets_range` | GET `/budget/expenses/?date_from=2025-01-01&date_to=2025-12-31` activates that range |
| `test_search_date_overrides_range` | Set Q1; type `date>=2020-01-01` in search; old expense appears |
| `test_export_link_uses_range` | Q2 selected; export link href contains `date_from=YYYY-04-01&date_to=YYYY-06-30` |
| `test_project_list_respects_range` | Jan project expense visible in Q1, not in Q3 |
| `test_project_charts_refresh` | Switching range triggers chart reload (verify spinner or new total) |
| `test_buddy_expense_list_respects_range` | Jan direct buddy expense visible in Q1, not in Q3 |
| `test_buddy_expense_search` | Search filters direct buddy expense list correctly |

### 11.3 Unit tests in `tests/unit/test_query_parser.py`

The file maintains an inline copy of the tokenizer to avoid importing Django. Add
`has_date_filter` as a local implementation (identical to the one in `query_parser.py`)
and test it:

```python
import re

def has_date_filter(query_str):
    return bool(re.search(r'\bdate\s*(?:==|[<>]=?)', query_str or ''))

def test_has_date_filter_lt():
    assert has_date_filter("date<2025-01-01")

def test_has_date_filter_gte():
    assert has_date_filter("date>=2024-06-01")

def test_has_date_filter_eq():
    assert has_date_filter("groceries date==2024-01-15 value<50")

def test_has_date_filter_false_plain_text():
    assert not has_date_filter("groceries type=expense")

def test_has_date_filter_false_empty():
    assert not has_date_filter("")

def test_has_date_filter_false_none():
    assert not has_date_filter(None)
```

Run with: `venv/bin/pytest tests/unit/test_query_parser.py -v`

### 11.4 Tests to update

| File | Change |
|---|---|
| `tests/e2e/test_data_export.py` | The expense list CSV export test checks `"month=" in href`. Change to `"date_from=" in href`. |
| `tests/e2e/test_dashboard_cards.py` | Uses `?year=...&month=...` API params directly. No change needed (backward compat). |
| `tests/e2e/buddies/test_project_expense_filters.py` | If it selects by `.add-buddy-panel`, update to `.exp-filter-panel`. |
| `tests/e2e/test_sharing_mode.py` | If it relies on `period-toggle__opt`, update for new nav. |

---

## 12. Documentation updates

All documentation is aimed at everyday (non-technical) users. No jargon.

### `docs/src/docs/user-manual/expenses.md`

Replace the section about "month view / year view" and navigation arrows with a
description of the date range picker:
- Briefly describe the preset buttons (financial month, year, quarters).
- Explain how to set a custom date range using the Start and End fields.
- Mention that the selection is remembered across pages and cleared with the Clear button.

### `docs/src/docs/user-manual/projects.md`

Add a note (a short paragraph or callout) stating that the expense breakdown, tag chart,
spending chart, and upfront-payer pie chart all use the selected date range. Clarify that
the debt totals and debt graphs always cover all project history.

### `docs/src/docs/user-manual/api-access.md`

Add documentation for `date_from` and `date_to` query params on `GET /api/v1/expenses/`:
- They accept ISO 8601 dates: `YYYY-MM-DD`.
- When provided, they take precedence over `year`, `month`, and `view`.
- Example: `GET /api/v1/expenses/?date_from=2026-01-01&date_to=2026-03-31`

---

## 13. File-by-file change summary

| File | Change |
|---|---|
| `budget/views/_period.py` | Add `_date_range_presets_context(feuser)` |
| `budget/query_parser.py` | Add `has_date_filter(query_str)` |
| `budget/views/expenses.py` | Use `_date_range_presets_context`; update export; remove old period helpers |
| `budget/views/dashboard.py` | Use `_date_range_presets_context`; remove old period helpers |
| `budget/views/dashboard_cards_api.py` | Support `date_from`/`date_to` in `_period_qs()` |
| `budget/dashboard_cards.py` | Skip period date filter when card query contains date operator |
| `api/views/expenses.py` | Support `date_from`/`date_to`; skip period filter when `has_date_filter()` |
| `buddies/views/projects.py` | Add `project_charts_data` view; add `_compute_project_charts`; update `project_expense_list_partial`; rename CSS class |
| `buddies/views/main.py` | Add `direct_expense_list_partial`; add `_compute_direct_expenses`; update `buddy_summary_page` |
| `buddies/urls.py` | Add `direct-expenses/partial/` URL |
| `buddies/urls_projects.py` | Add `charts-data/` URL |
| `templates/partials/_date_range_nav.html` | **New** — replaces `_month_nav.html` on all pages |
| `templates/partials/_month_nav.html` | Keep file unchanged; no page includes it anymore |
| `budget/templates/budget/expenses_list.html` | Switch to `_date_range_nav.html`; update JS config |
| `budget/templates/budget/dashboard.html` | Switch to `_date_range_nav.html`; update JS config |
| `buddies/templates/buddies/project_detail.html` | Add `_date_range_nav.html`; AJAX charts; rename CSS class; add date params to expense list fetch |
| `buddies/templates/buddies/buddy_summary.html` | Add `_date_range_nav.html`; replace direct expense list with AJAX container |
| `buddies/templates/buddies/direct_expense_partial.html` | **New** |
| `build/js/date-range.js` | **New** — `dateRange` singleton |
| `build/js/expenses.js` | Import `dateRange`; swap period params |
| `build/js/dashboard.js` | Import `dateRange`; swap period params |
| `build/scss/_date-range-nav.scss` | **New** |
| `build/scss/main.scss` | Import `_date-range-nav.scss` |
| `tests/e2e/test_period.py` | **Delete** |
| `tests/e2e/test_date_range.py` | **New** |
| `tests/unit/test_query_parser.py` | Add `has_date_filter` tests |
| `tests/e2e/test_data_export.py` | Update export href assertion |
| `tests/e2e/buddies/test_project_expense_filters.py` | Update `.add-buddy-panel` selector if present |
| `tests/e2e/test_sharing_mode.py` | Update if relying on old `period-toggle__opt` selector |
| `docs/src/docs/user-manual/expenses.md` | Rewrite period nav section |
| `docs/src/docs/user-manual/projects.md` | Add date range note |
| `docs/src/docs/user-manual/api-access.md` | Document `date_from`/`date_to` |

---

## 14. Out of scope

- Dashboard card editor UI (the YAML `query:` field lets users set date filters manually)
- Scheduled expenses page (no date range filtering exists there)
- Mobile layout specifics beyond responsive CSS
- Persisting the range across user accounts or devices (localStorage is per-device by design)
- The `expenses_export` in account-level ZIP export (that is a full-history export and not period-scoped)
