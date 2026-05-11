# Dashboard Cards: Configuration

Each card on your dashboard is configured using a small text recipe called YAML. It looks a bit like a list of settings, one per line. You do not need to know how to code; just follow the examples and change the values to suit your needs.

When you click **+ Add card** or the pencil icon on an existing card, an editor opens where you type (or paste) the configuration. Click **Save** and the card updates immediately.

## Card types

| `type` value | What it shows |
|---|---|
| `cell` | A single number: a total, a count, or a custom calculation. |
| `bar-chart` | Horizontal bars showing how spending is split across categories or tags. |
| `pie-chart` | A pie showing spending proportions across categories or tags. |
| `list` | A scrollable table listing individual expenses that match a query. |

## Fields that every card has

### `type` (required)

```yaml
type: cell
```

Sets the card style. Must be one of `cell`, `bar-chart`, `pie-chart`, or `list`.

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

The `method` field tells the card how to calculate its number. Different card types support different methods.

### `sum`

Adds up the value of all matching expenses. Every transaction counts as a positive number regardless of type.

```yaml
method: sum
query: type=expense
```

Good for: "How much did I spend on groceries?"

### `total`

Adds up values but treats income and savings withdrawals as negative contributors. This gives you a net balance.

```yaml
method: total
flip_signs: true
```

With `flip_signs: true`, this gives "money left to spend": income minus expenses. Good for the "left to spend" card.

### `count`

Counts how many matching expenses there are, rather than summing their values.

```yaml
method: count
query: settled=no
```

Good for: "How many bills am I still waiting to pay?"

### `custom`

Lets you write a small calculation yourself, using Python. Only available for cell cards. See [Cell Cards](cell.md) for details.

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

For all the extra options available to each type, see:

- [Cell Cards](cell.md)
- [Bar Chart Cards](bar-chart.md)
- [Pie Chart Cards](pie-chart.md)
- [List Cards](list.md)
