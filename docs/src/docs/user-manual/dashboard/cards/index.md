# Dashboard Cards: Configuration

Each card on your dashboard is configured using a small text recipe called YAML. It looks a bit like a list of settings, one per line. You do not need to know how to code; just follow the examples and change the values to suit your needs.

When you click **+ Add card** or the pencil icon on an existing card, an editor opens where you type (or paste) the configuration. Click **Save** and the card updates immediately.

If you don't want to write the YAML yourself, look for **"... OR let AI create the card for you"** below the editor (this only appears if AI features are available on your account). Describe what you want in plain language, for example *"The card should show how much I spent on Amazon this month"*, and click **Generate with AI**. It fills in the editor for you, ready to review, tweak and save. The AI also sees your other cards so the new one fits the same style, and your categories, tags and projects so it can filter correctly. When editing an existing card, describe the change instead, for example *"Modify this card to also include savings withdrawals"*.

## Card types

| `type` value | What it shows |
|---|---|
| `cell` | A single number: a total, a count, or a custom calculation. |
| `bar-chart` | Horizontal bars showing how spending is split across categories or tags. |
| `pie-chart` | A pie showing spending proportions across categories or tags. |
| `line-chart` | One or more lines plotted over time, showing how money moves day by day or week by week. |
| `list` | A scrollable table listing individual expenses that match a query. |
| `spacer` | An invisible placeholder that reserves space in the grid. Useful for alignment and visual gaps. |

## Fields that every card has

### `type` (required)

```yaml
type: cell
```

Sets the card style. Must be one of `cell`, `bar-chart`, `pie-chart`, `list`, `line-chart`, or `spacer`.

---

### `title` (required)

```yaml
title: Monthly income
```

The label shown at the top of the card.

---

### `query`

```yaml
query: type=expense settled=no
```

A filter that limits which expenses this card counts. Uses the same language as the expense search bar. See [Search & Filters](../query-language.md). If you leave this out, the card counts all expenses in the current period.

---

### `flip_signs`

```yaml
flip_signs: true
```

Multiplies the result by -1. Useful when a calculation naturally comes out negative but you want to display it as a positive "money left" figure. Default: `false`.

---

## Positioning: where the card sits on the grid

Every card has a `positioning` block that controls its position and size.

```yaml
positioning:
  position: 0
  width: 4
  height: 2
```

| Field | What it does | Default |
|---|---|---|
| `position` | The order the card appears in. Lower numbers come first. | 0 |
| `width` | How many columns wide the card is. On desktop, the grid is 12 columns wide. | 2 |
| `height` | How many rows tall the card is. Each row is about 90 px. | 1 |

You do not actually need to worry about this, since you can automatically populate these by dragging cards around
and by resizing them with your mouse cursor.

### Separate sizing for phones

You can give a card a different size and position on mobile by adding a `mobile` block inside `positioning`:

```yaml
positioning:
  position: 0
  width: 6
  height: 2
  mobile:
    position: 0
    width: 6
    height: 3
```

The mobile layout uses a 6-column grid. On a phone screen, the `mobile` values take over; on a larger screen, the desktop values are used.

If you do not add a `mobile` block, the card uses the desktop values on both screen sizes (capped at 6 columns on mobile).

---

## Computation methods

The `method` field controls how a card calculates its value. Its meaning depends on the card type, because different types need different kinds of computation.

### Cell and list cards

Cell cards compute a single number. List cards use `method` only to calculate the optional summary row.

| `method` | What it calculates |
|---|---|
| `sum` | Adds up all matching values. Every transaction type counts as positive. |
| `total` | Adds up values but treats income and savings withdrawals as negative. Good for a net-balance figure. |
| `count` | Counts how many matching expenses there are instead of summing values. |

Default for cell and list cards: `sum`.

#### Example: total spent on groceries

```yaml
method: sum
query: type=expense
```

#### Example: money left to spend

```yaml
method: total
flip_signs: true
```

Income minus expenses, displayed as a positive number.

#### Example: outstanding bill count

```yaml
method: count
query: settled=no
```

---

### Bar chart and pie chart cards

Bar and pie charts support the same two `method` values as the numeric methods above, applied per group:

| `method` | What it calculates |
|---|---|
| `sum` | Total value of expenses in that group. Every type is positive. Default. |
| `total` | Net value: income and savings withdrawals count negative. |

---

### Line chart cards

Line charts use `method` at the card level to decide how each time bucket is built:

| `method` | What it plots |
|---|---|
| `cum` | Cumulative running total up to each point. The line never dips. Default. |
| `base` | Only the activity within each bucket (one day in month view, one week in year view). |

Each individual series inside a line chart also has its own `method` field (separate from the card-level one) that controls aggregation: `sum` or `total`.
In line charts, `flip_signs` only exists on series-level.

See [Line Chart Cards](line-chart.md) for details.

---

## Minimal examples

The simplest possible cell card:

```yaml
type: cell
title: Total spending
method: sum
query: type=expense
positioning:
  position: 0
  width: 3
  height: 1
```

The simplest bar chart:

```yaml
type: bar-chart
title: Spending by category
group: categories
positioning:
  position: 5
  width: 6
  height: 4
```

The simplest list card:

```yaml
type: list
title: Today's expenses
query: type=expense date=today
positioning:
  position: 10
  width: 4
  height: 3
```

The simplest line chart:

```yaml
type: line-chart
title: Spending over time
method: cum
series:
  - label: Expenses
    query: type=expense
positioning:
  position: 15
  width: 6
  height: 3
```

For all the extra options available to each type, see:

- [Cell Cards](cell.md)
- [Bar Chart Cards](bar-chart.md)
- [Pie Chart Cards](pie-chart.md)
- [List Cards](list.md)
- [Line Chart Cards](line-chart.md)
- [Spacer Cards](spacer.md)
