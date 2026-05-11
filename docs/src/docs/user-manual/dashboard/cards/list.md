# List Cards

A list card shows a scrollable table of individual expenses that match your query, one row per expense. Each row displays a short type abbreviation, the expense title, and its value.

```yaml
type: list
title: Today's expenses
query: type=expense date=today
order_by: value
order_dir: desc
positioning:
  position: 4
  width: 4
  height: 3
```

## Row format

Each row contains three columns:

| Column | Content |
|---|---|
| Type | Two-letter abbreviation (see below) |
| Title | The expense title, truncated if too long |
| Value | Rounded value followed by your currency symbol |

### Type abbreviations

| Type | Abbreviation |
|---|---|
| Expense | `EX` |
| Income | `IN` |
| Savings Deposit | `SD` |
| Savings Withdrawal | `SW` |
| Carry-Over | `CO` |

## Sorting

### `order_by`

```yaml
order_by: value
```

Which field to sort by. Options: `value`, `date`, `title`. Default: `date`.

### `order_dir`

```yaml
order_dir: desc
```

Sort direction. `asc` for ascending, `desc` for descending. Default: `desc`.

## Type colours

```yaml
type_colors: false
```

By default each row is tinted with the colour associated with its expense type (green for income, red for expenses, etc.). Set `type_colors: false` to disable all row colouring.

## Summary row

```yaml
show_sum: true
method: sum
```

When `show_sum: true`, a summary row appears above the list. Its content is computed using `method`:

| `method` | What it calculates |
|---|---|
| `sum` | Plain sum of all matching values. |
| `total` | Sum where income and savings withdrawals count as negative. |
| `count` | Number of matching entries (no currency colouring). |

Default method: `sum`.

The summary value is coloured green for positive, red for negative, unless `type_colors: false` or `method: count`.

### `flip_signs`

```yaml
flip_signs: true
```

Multiplies the summary value by -1 before display and before the sign-based colour is applied.

### `sum_template`

```yaml
sum_template: "$VALUE orders"
```

Controls how the summary row is displayed. Supports two placeholders:

| Placeholder | Replaced with |
|---|---|
| `$VALUE` | The computed value (rounded to integer) |
| `$CURRENCY_SYMBOL` | Your account currency symbol |

Default: `$VALUE $CURRENCY_SYMBOL`.

## Full example

```yaml
type: list
title: Outstanding bills
query: type=expense settled=no
order_by: value
order_dir: desc
show_sum: true
method: sum
sum_template: "Total: $VALUE $CURRENCY_SYMBOL"
positioning:
  position: 3
  width: 4
  height: 4
```
