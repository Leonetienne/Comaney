# Line Chart Cards

A line chart card plots one or more data series over time. In month view each point represents one day; in year view each point represents one week. Use it to see how spending accumulates through the month, or to compare multiple streams of money side by side.

For the fields every card shares (type, title, query, positioning), see [Dashboard Cards: Configuration](index.md).

## Extra fields for line chart cards

| Field | Required | What it does                                                                               |
|---|---|--------------------------------------------------------------------------------------------|
| `series` | Yes | The list of lines to draw. Each entry is one line on the chart.                            |
| `method` | No | `cum` (Cumulative) or `base` (Basic). Controls how time buckets are built. Default: `cum`. |
| `render_type` | No | `smooth` or `linear`. Controls how the line is drawn between points. Default: `smooth`. |
| `suggested_min` | No | Soft lower bound for the Y axis. Expands further if data goes lower. |
| `suggested_max` | No | Soft upper bound for the Y axis. Expands further if data goes higher. |
| `limit_min` | No | Hard lower cut-off. The axis never goes below this, even if data does. |
| `limit_max` | No | Hard upper cut-off. The axis never goes above this, even if data does. |

---

## `method` (card level)

```yaml
method: cum
```

This controls how the Y axis is built across time.

- `cum`: cumulative. Each point shows the running total up to that day or week. Good for "how much have I spent up to this point?"
- `base`: per-bucket. Each point shows only the activity within that time window. Good for "which days did I spend the most?"

---

## `render_type`

```yaml
render_type: smooth
```

Controls the shape of the line between data points.

- `smooth`: the line curves gently between points (default).
- `linear`: the line goes straight from point to point with no curve.

---

## Y-axis bounds

```yaml
suggested_min: -500
suggested_max: 1000
limit_min: -1000
limit_max: 2000
```

All four fields are optional and can be combined freely. If none are set, the Y axis scales automatically to fit the data.

- `suggested_min` / `suggested_max`: create headroom. The axis will reach at least this far, but expands beyond it if any data point requires more room.
- `limit_min` / `limit_max`: hard cut-offs. The axis never goes beyond these values, even if data does.

---

## `series`

```yaml
series:
  - label: Expenses
    query: type=expense
    method: sum
    color: "#e05252"
  - label: Income
    query: type=income
    method: sum
    color: "#52a852"
```

`series` is a list. Each entry draws one line. At least one entry is required.

### Per-series fields

| Field | Required | What it does |
|---|---|---|
| `label` | Yes | The name shown in the chart legend and tooltip. |
| `query` | No | An additional filter for this series. Combined with the card-level `query`. |
| `method` | No | `sum` or `total`. Controls how values are aggregated within each bucket. Default: `sum`. |
| `flip_signs` | No | Multiplies this series' values by -1. Useful for showing a cost as a negative line. Default: `false`. |
| `link_template` | No | A URL to navigate to when a data point on this series is clicked. |
| `color` | No | A hex colour for this line. If omitted, a colour is derived automatically from the label. |

#### Per-series `method`

- `sum`: adds up all matching values. Every type counts as positive.
- `total`: income and savings withdrawals count as negative. Good for a net-balance line.

This is separate from the card-level `method` (which controls cumulative vs per-bucket). Both can be set independently.

---

#### `link_template`

```yaml
series:
  - label: Expenses
    query: type=expense
    link_template: "/budget/expenses/?search=type%3Dexpense+date%3E%3D$START_DATE+date%3C%3D$END_DATE"
```

When set, clicking a data point on this series navigates to the URL, with two placeholders substituted:

| Placeholder | Replaced with |
|---|---|
| `$START_DATE` | The first day of the clicked bucket (`YYYY-MM-DD`) |
| `$END_DATE` | The last day of the clicked bucket (`YYYY-MM-DD`) |

In month view both dates are the same day. In year view they span a 7-day window.

The cursor changes to a pointer when hovering over a clickable data point.

---

## Time buckets

- **Month view**: one bucket per calendar day, from the start of the financial month up to today (or the end of the month, whichever comes first).
- **Year view**: one bucket per week (7-day intervals from the start of the financial year), up to today.

Buckets in the future are not shown. This means a line chart in month view during the first week of the month will only show a few data points.

---

## X-axis labels

Dates on the X axis are displayed in a short format such as `19. Oct` or `02. Feb`. Because there can be many points, only a subset of labels is shown; the others are skipped automatically to avoid overlap. Labels are displayed at a slight angle.

---

## Complete examples

### Cumulative spending vs income

```yaml
type: line-chart
title: Spending vs Income
method: cum
series:
  - label: Expenses
    query: type=expense
    color: "#e05252"
  - label: Income
    query: type=income
    color: "#52a852"
positioning:
  position: 5
  width: 6
  height: 3
```

### Left to spend over time

```yaml
title: Left to spend
type: line-chart
method: cum
positioning:
  height: 3
  mobile:
    height: 3
    position: 8
    width: 6
  position: 8
  width: 4
series:
- color: '#2887f3'
  flip_signs: true
  label: Left to spend
  link_template: /budget/expenses/?search=date>=$START_DATE+date<=$END_DATE
  method: total

```

### Daily expenses this month, without rent

```yaml
type: line-chart
title: Daily expenses
method: base
series:
  - label: Spending
    query: type=expense !rent
    method: sum
    color: "#c45"
positioning:
  position: 10
  width: 6
  height: 3
```
