# TICKET-01 — Out-of-range `year` query parameter crashes budget views (HTTP 500 / DoS)

**Severity:** High (authenticated denial of service; unhandled 500s)
**Type:** Robustness / crash
**Components:** `budget/views/_period.py`, `budget/date_utils.py`, `api/utils.py`

## Summary

Several authenticated endpoints accept a `year` (and `month`) value from the query
string and pass it into `datetime.date(...)` without bounding it to Python's valid
year range (1–9999). Supplying a `year` of `10000` or larger (or `year=1` for a user
whose financial month starts in the previous calendar month) raises an unhandled
`ValueError`, which Django turns into an HTTP 500.

Any logged-in user can trigger it, e.g.:

```
GET /budget/dashboard/cards/?view=year&year=10000
GET /budget/expenses/export/?view=year&year=999999999
GET /api/expenses/?view=year&year=10000      (Bearer or session auth)
```

## Reproduction

Verified directly against the date helpers:

```
$ ./venv/bin/python3 -c "from budget.date_utils import financial_year_range; financial_year_range(10000,1,False)"
ValueError: year 10000 is out of range

$ ./venv/bin/python3 -c "from budget.date_utils import financial_month_range; financial_month_range(1,1,27,True)"
ValueError: year 0 is out of range
```

## Root cause

`budget/views/_period.py`:

```python
def _get_year(request, start_day=1, prev_month=False) -> int:
    try:
        year = int(request.GET["year"])
        if year < 1:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return current_financial_month(start_day, prev_month)[0]
    return year          # <-- only the int() parse is guarded, not the value's usability
```

The returned `year` is then handed to `financial_year_range(year, ...)` /
`financial_month_range(year, month, ...)`, which call `date(year, month, day)`.
`int("10000")` succeeds, so the guard passes, but `date(10000, ...)` throws.
`_get_month` (same file) and `_parse_month` in `api/utils.py` have the identical gap.
Note also the lower edge: `financial_month_range` computes `py = year - 1` when
`month == 1`, so `year=1` with `prev_month=True` reaches `date(0, ...)`.

Date-string inputs (`date_from`/`date_to`) are *not* affected, because
`date.fromisoformat` only accepts 4-digit years and already rejects the rest.

## Affected call sites

- `budget/views/_period.py:_get_year` / `_get_month`
- `budget/views/expenses.py:244-249` (`expenses_export`)
- `budget/views/dashboard_cards_api.py:72-76` (`cards_api` GET → dashboard data)
- `api/utils.py:_parse_month` (used by `api/views/expenses.py`, scheduled, etc.)
- Any dashboard/expenses page that resolves a period from `?year=`

## Proposed fix

Bound the accepted year to a sane range in the parse helpers, falling back to the
current financial year when out of range. Centralize the bound so all callers benefit.

```python
_MIN_YEAR = 2
_MAX_YEAR = 9998   # leave head-room: prev/next month math touches year ± 1

def _get_year(request, start_day=1, prev_month=False) -> int:
    try:
        year = int(request.GET["year"])
        if not (_MIN_YEAR <= year <= _MAX_YEAR):
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return current_financial_month(start_day, prev_month)[0]
    return year
```

Apply the same clamp in `_get_month` and in `api/utils._parse_month`. Using
`_MIN_YEAR = 2` / `_MAX_YEAR = 9998` avoids the `year ± 1` off-by-one at the
boundaries inside `financial_month_range`.

Optionally, add defense-in-depth by catching `ValueError` inside
`financial_month_range`/`financial_year_range` and clamping, but input validation
at the boundary is the primary fix.

## Regression testing

- **Unit** (`tests/unit/`, no DB): parametrized test over `_get_year`/`_get_month`
  and `_parse_month` with `year` values `{ "0", "1", "10000", "999999999", "abc",
  "-5", "" }` asserting they fall back to the current financial year rather than
  raising. Add a direct test that `financial_year_range`/`financial_month_range`
  never raise for the clamped bounds and for `prev_month=True`.
- **Regression guard**: a test that builds a fake request with `year=10000` and
  calls the period helpers, asserting no exception.
- **E2E** (optional): `GET /budget/dashboard/cards/?view=year&year=10000` returns
  200 (not 500) for a logged-in user.
