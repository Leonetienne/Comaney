# Bar Chart Cards

A bar chart card shows a list of horizontal bars, one for each category or tag, sorted from largest to smallest. It is great for seeing at a glance where your money is going across different groups.

For the fields every card shares (type, title, query, positioning), see [Dashboard Cards: Configuration](index.md).

## Extra fields for bar chart cards

| Field | Required | What it does |
|---|---|---|
| `group` | Yes | Whether to group by `categories` or `tags`. |
| `method` | No | `sum` or `total`. Default: `sum`. |
| `max_groups` | No | Limit the chart to the top N bars. |
| `hide_groups` | No | A list of group names to leave out of the chart. |
| `link_template` | No | A URL to navigate to when someone clicks a bar. |

---

## `group` (required)

```yaml
group: categories
```

or

```yaml
group: tags
```

This decides how the bars are divided up. Each unique category (or tag) becomes one bar. Expenses that have no category or tag appear under an **Uncategorized** bar.

**Which should you use?**

- **Categories** work best if you want to see spending by broad area: Housing, Groceries, Transport.
- **Tags** work well when you want to see spending by payment method, shop, or any cross-cutting label. Because an expense can have multiple tags, one purchase can appear in more than one bar, which is intentional and useful.

---

## `method`

```yaml
method: sum
```

- `sum`: adds up all amounts. Every transaction type counts as positive. Good for showing total spending volume per group.
- `total`: income and savings withdrawals count as negative. Good when your query mixes income and expenses and you want the net amount per group.

---

## `max_groups`

```yaml
max_groups: 8
```

Limits the chart to the top N bars by value. Extra bars are not shown. Useful for keeping the chart tidy when you have many categories or tags.

---

## `hide_groups`

```yaml
hide_groups:
  - Uncategorized
  - Amazon
```

A list of group names to exclude entirely. The match is case-insensitive. Handy for hiding noise, like the tag you already used in the `query` filter (which would otherwise appear as a 100% bar, which is not informative).

---

## `link_template`

```yaml
link_template: /budget/expenses/?search=cat%3D$GROUP_NAME
```

When set, clicking a bar takes you to this URL, with `$GROUP_NAME` replaced by the name of that bar's group. For the **Uncategorized** bar, `$GROUP_NAME` becomes `none`.

**Common link templates:**

```yaml
# When grouping by category
link_template: /budget/expenses/?search=cat%3D$GROUP_NAME

# When grouping by tag
link_template: /budget/expenses/?search=tag%3D$GROUP_NAME
```

---

## Complete examples

### Spending by category

```yaml
type: bar-chart
title: Spending by category
group: categories
query: type=expense
link_template: /budget/expenses/?search=cat%3D$GROUP_NAME+type%3Dexpense
positioning:
  position: 3
  width: 6
  height: 4
```

### Top 5 spending tags

```yaml
type: bar-chart
title: Top 5 tags
group: tags
query: type=expense
max_groups: 5
link_template: /budget/expenses/?search=tag%3D$GROUP_NAME+type%3Dexpense
positioning:
  position: 6
  width: 6
  height: 4
```

### Income by category

```yaml
type: bar-chart
title: Income by category
group: categories
query: type=income
method: sum
link_template: /budget/expenses/?search=type%3Dincome+cat%3D$GROUP_NAME
positioning:
  position: 12
  width: 6
  height: 3
```
