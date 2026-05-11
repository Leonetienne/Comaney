# Cell Cards

A cell card shows a single number on your dashboard: a total, a count, a balance, or any figure you want to see at a glance. It is the most common card type.

For the fields every card shares (type, title, query, positioning), see [Dashboard Cards: Configuration](index.md).

## Extra fields for cell cards

| Field | What it does |
|---|---|
| `method` | **Required.** How to calculate the number. See [computation methods](index.md#computation-methods). |
| `color` | Background colour of the card (works in both light and dark mode). |
| `color_lightmode` | Overrides `color` when the browser is in light mode. |
| `color_darkmode` | Overrides `color` when the browser is in dark mode. |
| `color_breakpoints` | Changes the card colour automatically based on the value. |
| `link` | A URL to navigate to when someone clicks the card body. |
| `template` | Controls how the number is displayed (for example: "€ 142.50 left"). |
| `python` | A custom calculation, for `method: custom` only. |

---

## Colours

```yaml
color: '#1a3326'
color_lightmode: '#bbf7d0'
color_darkmode: '#0f2a1e'
```

- `color` sets the card background in both light and dark mode.
- `color_lightmode` overrides it when the user is in light mode.
- `color_darkmode` overrides it when the user is in dark mode.

You can use any colour: a hex code like `#1a3326`, an `rgb()` value, a named colour like `green`, and so on.

If you only set `color`, it applies to both modes. If you set `color` and `color_lightmode`, dark mode uses `color` and light mode uses `color_lightmode`.

**Some ready-to-use colour pairs:**

| Character | Dark mode | Light mode |
|---|---|---|
| Green: income, savings | `#1a3326` | `#bbf7d0` |
| Blue: informational | `#1e2a3a` | `#bfdbfe` |
| Red: overspending | `#3b0a0a` | `#fecaca` |
| Amber: caution | `#292217` | `#fde68a` |

---

## Colour breakpoints: cards that change colour automatically

Breakpoints let the card change colour based on its current value. For example, a "money left" card can turn amber when funds are running low, and red when you are in the negative.

```yaml
color_breakpoints:
  - less_than: 200
    color: '#292217'
    color_lightmode: '#fde68a'
  - less_than: 0
    color: '#3b0a0a'
    color_lightmode: '#fecaca'
```

Each breakpoint says: "if the value is less than X, use this colour." The breakpoints are checked in order from top to bottom, and the last one that matches wins.

In the example above:

- Value is 350: no breakpoint matches, so the card's base colour is used (green).
- Value is 150: the first breakpoint matches (150 < 200), so amber is used.
- Value is -20: both breakpoints match (-20 < 200, -20 < 0), but the last match wins, so red is used.

Each breakpoint supports the same colour fields as the card root: `color`, `color_lightmode`, `color_darkmode`.

---

## Link

```yaml
link: /budget/expenses/?search=type%3Dincome
```

When set, clicking anywhere on the card body takes you to that URL. Useful for jumping to a filtered expense list directly from the dashboard.

---

## Template: customising the displayed text

By default, the card shows the number followed by the currency symbol: `142.50 €`. The `template` field lets you change this.

```yaml
template: '$VALUE $CURRENCY_SYMBOL remaining'
```

| Placeholder | What it becomes |
|---|---|
| `$VALUE` | The calculated number, formatted with two decimal places |
| `$CURRENCY_SYMBOL` | Your currency symbol (€, $, £, etc.) |

**Examples:**

| Template | Displays as |
|---|---|
| `$VALUE $CURRENCY_SYMBOL left` | `142.50 € left` |
| `$CURRENCY_SYMBOL $VALUE` | `€ 142.50` |
| `$VALUE` | `142.50` (no currency symbol) |

---

## Custom calculations (`method: custom`)

If the built-in `sum`, `total`, and `count` methods are not enough, you can write your own small calculation.

```yaml
method: custom
python: |
  income = query_sum('type=income')
  expenses = query_sum('type=expense')
  savings = query_sum('type="savings deposit"')
  withdrawals = query_sum('type="savings withdrawal"')
  return income - expenses - savings + withdrawals
```

Inside the `python` block you have access to four helpers:

| Helper | What it returns |
|---|---|
| `query_sum('...')` | The sum of all matching expenses for the current period |
| `query_sum_abs('...')` | Same, but always positive |
| `query_sum_gt0('...')` | Sum of matching expenses where the value is positive |
| `query_sum_lt0('...')` | Sum of matching expenses where the value is negative |

The text inside the quotes uses the same filter language as the search bar. See [Search & Filters](../query-language.md).

---

## Full examples

### Income card

```yaml
type: cell
title: Income
method: sum
query: type=income
color: '#1a3326'
color_lightmode: '#bbf7d0'
link: /budget/expenses/?search=type%3Dincome
positioning:
  position: 0
  width: 2
  height: 1
```

### Money left to spend (turns amber then red as funds run low)

```yaml
type: cell
title: Left to spend
method: total
flip_signs: true
color: '#1a3326'
color_lightmode: '#a7f3d0'
color_breakpoints:
  - less_than: 200
    color: '#292217'
    color_lightmode: '#fde68a'
  - less_than: 0
    color: '#3b0a0a'
    color_lightmode: '#fecaca'
positioning:
  position: 1
  width: 2
  height: 1
```

### Count of unpaid bills

```yaml
type: cell
title: Outstanding payments
method: count
query: settled=no type=expense
template: $VALUE bills unpaid
link: /budget/expenses/?search=settled%3Dno+type%3Dexpense
positioning:
  position: 4
  width: 2
  height: 1
```

### Total savings with custom display text

```yaml
type: cell
title: Total savings this month
method: sum
query: type="savings deposit"
template: '$CURRENCY_SYMBOL $VALUE saved'
positioning:
  position: 6
  width: 3
  height: 1
```
