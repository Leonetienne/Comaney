# Pie Chart Cards

A pie chart card shows your spending as slices of a circle, so you can immediately see which categories take the biggest share of your budget.

For the fields every card shares (type, title, query, positioning), see [Dashboard Cards: Configuration](index.md).

## Extra fields for pie chart cards

| Field | Required | What it does |
|---|---|---|
| `group` | Yes | Whether to group by `categories` or `tags`. |
| `method` | No | `sum` or `total`. Default: `sum`. |
| `hide_groups` | No | A list of group names to leave out of the chart. |
| `link_template` | No | A URL to navigate to when someone clicks a slice. |

!!! note
    Pie charts do not support `max_groups`. If you have many groups, consider using a [bar chart](bar-chart.md) instead, which does support limiting the number of bars.

---

## `group` (required)

```yaml
group: categories
```

or

```yaml
group: tags
```

**Which should you use?**

Pie charts work best with **categories**. Because every expense belongs to exactly one category, the slices add up to a clean 100% and the proportions are meaningful.

Avoid grouping by tags in a pie chart. Since a single expense can carry multiple tags, one purchase could be counted in several slices at once, making the percentages misleading.

---

## `method`

```yaml
method: sum
```

- `sum`: adds up all amounts. Every transaction type counts as positive.
- `total`: income and savings withdrawals count as negative. Less common for pie charts, but available when needed.

---

## `hide_groups`

```yaml
hide_groups:
  - Uncategorized
  - Transfer
```

Excludes named groups from the chart. The match is case-insensitive. Useful for removing slices that would clutter the legend.

---

## `link_template`

```yaml
link_template: /budget/expenses/?search=cat%3D$GROUP_NAME
```

When set, clicking a slice takes you to this URL, with `$GROUP_NAME` replaced by the name of that slice's group. For the **Uncategorized** slice, `$GROUP_NAME` becomes `none`.

---

## Visual notes

- The legend appears below the chart.
- Colours are drawn from a fixed set of 15. If you have more groups than colours, the palette repeats.
- The chart adapts to light and dark mode automatically.
- Use at least `height: 3` so the chart and legend have enough room. Smaller cards may clip the chart.

---

## Complete examples

### Expenses by category

```yaml
type: pie-chart
title: Expenses by category
group: categories
query: type=expense
link_template: /budget/expenses/?search=cat%3D$GROUP_NAME+type%3Dexpense
positioning:
  position: 3
  width: 6
  height: 4
```

### Income sources

```yaml
type: pie-chart
title: Income sources
group: categories
query: type=income
method: sum
link_template: /budget/expenses/?search=type%3Dincome+cat%3D$GROUP_NAME
positioning:
  position: 13
  width: 4
  height: 4
```
