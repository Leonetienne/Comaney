# Gauge Cards

A gauge card shows progress toward a limit as a filling arc, like a speedometer. It is built for budgets and caps: "I want to spend at most 200 € on Amazon this month" becomes a gauge that fills up as you spend, so you can see at a glance how close you are to the limit.

For the fields every card shares (type, title, query, positioning), see [Dashboard Cards: Configuration](index.md).

## Extra fields for gauge cards

| Field | What it does |
|---|---|
| `method` | **Required.** How to calculate the current value. See [computation methods](index.md#computation-methods). |
| `max_value` | A fixed number for the gauge's maximum. |
| `max_value_query` | Instead of a fixed number, calculate the maximum from a query (for example, your income this month). Requires `max_value_method`. |
| `max_value_method` | How to calculate `max_value_query`'s result: `sum`, `total`, or `count`. |
| `show_raw_values` | Show the current value and the maximum as text, like `120 / 200 €`. Default `true`. |
| `show_percent` | Show the current value as a percentage of the maximum, like `60%`. Default `true`. |
| `gauge_color` | Colour of the filled arc and the number (both light and dark mode). |
| `gauge_color_lightmode` | Overrides `gauge_color` when the browser is in light mode. |
| `gauge_color_darkmode` | Overrides `gauge_color` when the browser is in dark mode. |
| `color_breakpoints` | Changes the gauge's colour automatically based on how close to the maximum it is (as a percentage). |
| `link` | A URL to navigate to when someone clicks the card body. |

Unlike a cell card, a gauge always needs a `query`: it is what the gauge measures progress against.

---

## The maximum: fixed or dynamic

Every gauge needs a maximum, set in one of two ways. You must use exactly one of them, not both.

### A fixed number

```yaml
max_value: 200
```

Use this when the limit is a number you choose yourself, like a monthly spending cap.

### Calculated from a query

```yaml
max_value_query: type=income
max_value_method: sum
```

Use this when the limit should move with your finances instead of staying fixed, for example "spend no more than I earned this month." `max_value_query` uses the same search language as the expense search bar (see [Search & Filters](../query-language.md)), and `max_value_method` controls how its matches are combined, the same way `method` does for the current value.

---

## Full example: how much of my income did I spend?

```yaml
type: gauge
title: Income spent
query: type=expense
method: sum
max_value_query: type=income
max_value_method: sum
show_raw_values: true
show_percent: true
gauge_color: '#da2525'
gauge_color_lightmode: '#da2525'
color_breakpoints:
  - less_than: 100
    color: '#ffc800'
    color_lightmode: '#ffc800'
  - less_than: 10
    color: '#57a87e'
    color_lightmode: '#57a87e'
link: /budget/expenses/
positioning:
  position: 11
  width: 3
  height: 2
  mobile:
    position: 11
    width: 6
    height: 2
```

This gauge sums every expense this month and uses that month's total income as the maximum, so the cap moves with your finances instead of staying fixed. It also gets redder the more is spent: see [Colour breakpoints](#colour-breakpoints) below for how `gauge_color` and `color_breakpoints` work together to achieve that.

### Full example: a fixed spending cap

```yaml
type: gauge
title: Amazon budget
query: tag=amazon
method: sum
max_value: 200
show_percent: true
positioning:
  position: 8
  width: 3
  height: 2
```

Use a fixed `max_value` instead of `max_value_query` when the limit is a number you choose yourself rather than something calculated from your finances.

---

## Showing values

`show_raw_values` and `show_percent` are independent; both default to `true`. Set either to `false` to hide it.

| `show_raw_values` | `show_percent` | What's shown |
|---|---|---|
| `true` | `true` | `120 / 200 €` and, underneath, `60%` (default) |
| `true` | `false` | `120 / 200 €` only |
| `false` | `true` | `60%` only |
| `false` | `false` | Just the arc, no text |

The percentage shown is the true current-value-over-maximum ratio: if you go over the limit, it can read above `100%` even though the arc itself stops filling at the top.

---

## Colours

```yaml
gauge_color: '#1a3326'
gauge_color_lightmode: '#16a34a'
gauge_color_darkmode: '#4ade80'
```

`gauge_color` sets the colour of the filled arc and the number in both light and dark mode; `gauge_color_lightmode` / `gauge_color_darkmode` override it per mode. If you set nothing, the gauge uses a neutral grey.

### Colour breakpoints

```yaml
color_breakpoints:
  - less_than: 100
    color: '#fbbf24'
  - less_than: 20
    color: '#ef4444'
```

The mechanics are the same rule used by [cell cards](cell.md#colour-breakpoints-cards-that-change-colour-automatically): each entry says "if X is less than this threshold, use this colour," checked top to bottom, with the last matching entry winning, and `gauge_color` is the colour used when no breakpoint matches.

**The "X" is different, though.** Cell cards compare against the card's raw computed value. Gauge cards compare against the **percentage of the maximum reached** (the same number `show_percent` displays, so it can go above `100` if you're over the cap). This is so a threshold like `less_than: 10` means the same thing -- "under 10% of the cap" -- no matter what `max_value` actually is, instead of meaning something different on every gauge.

That "less than" direction is naturally suited to gauges where less is worse, like money remaining. For a "money spent so far" gauge, where *more* is worse, flip it around: make `gauge_color` the alarming colour (it applies whenever spending is high enough that no breakpoint matches), and use `color_breakpoints` to switch to progressively *safer* colours as the percentage drops. The "Income spent" example above does exactly this:

```yaml
gauge_color: '#da2525'                # red -- the default, shown once spending is high
gauge_color_lightmode: '#da2525'
color_breakpoints:
  - less_than: 100                    # under 100% of the cap -> amber
    color: '#ffc800'
    color_lightmode: '#ffc800'
  - less_than: 10                     # under 10% of the cap -> green (last match wins)
    color: '#57a87e'
    color_lightmode: '#57a87e'
```

Under 10% spent shows green, 10-99% shows amber, and 100% or more (at or over the cap) shows red: the gauge gets redder as it approaches its maximum.

---

## Link

```yaml
link: /budget/expenses/?search=tag%3Damazon
```

Works exactly like a cell card's `link`: clicking anywhere on the card body navigates there.
