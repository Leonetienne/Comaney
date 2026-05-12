# Dashboard

The dashboard is a fully customisable grid of cards. Each card is a self-contained widget that computes and displays financial data for the currently selected period.

## Period selection

The period selector at the top of the dashboard switches between **month view** and **year view**. In month view, all cards show data for the selected financial month. In year view, all cards aggregate across all 12 financial months of the selected year. Navigate between periods using the prev/next arrows.

## Managing cards

Upfront: Your dashboard already comes with a pre-made set of cards. The following is only relevant if you plan on customizing your dashboard.

### Adding a card

Click **+ Add card** to open the card editor. You can:

- **Start from a preset**: pick one of the built-in templates from the preset list. The YAML editor is pre-filled with the preset's configuration, which you can modify before saving.
- **Write YAML**: type or paste a card definition directly. See [Cards: YAML Structure](cards/index.md) for the schema.

Click **Save** to create the card. The new card appears at the end of the grid.

### Editing a card

Click the pencil icon on any card to open its YAML in the editor. Modify the YAML and click **Save**. The card re-renders immediately with the updated configuration.

### Reordering cards

Drag any card by its header to reorder it. Desktop and mobile orders are independent.

### Resizing a card

Drag the resize handle (bottom-right corner of each card) to change its width and height.
Resizing on a narrow screen updates the mobile layout; resizing on a wide screen updates the desktop layout.
Desktop and mobile sizes are independent.

### Deleting a card

Click the trash icon on any card. A confirmation dialog appears before deletion.

### Resetting to defaults

Click **Reset dashboard** (below the card grid) to delete all your cards and restore the original set of default cards. A confirmation dialog appears before the reset is applied.

## Types of cards

### Cells

A cell shows a single number: your total spending, remaining budget, number of outstanding payments, or any other figure you want to track at a glance. Cells are the most common card type and are great for the headline numbers you want to see the moment you open the dashboard.

See [Cell Cards](cards/cell.md) to learn how to configure one.

### List cards

A list card shows a scrollable table of individual expenses that match a query: one row per expense with a type abbreviation, title, and value. Optionally a summary row at the top shows the total.

See [List Cards](cards/list.md) for configuration options.

### Charts

Charts show how your money moves over time or how it is distributed across your categories or tags.

#### Bar chart

A bar chart shows one horizontal bar per group, with the largest bar at the top. Each bar represents the total spending for that category or tag.

Bar charts are a good fit for **tags**. Because you can apply multiple tags to a single expense, one purchase can show up in several bars at once, which is exactly what you want when you are asking "how much did I spend on Amazon?" and "how much did I spend on the credit card?" at the same time.

Clicking a bar takes you to the expense list filtered to that group (if the card is configured to do so).

See [Bar Chart Cards](cards/bar-chart.md) for configuration options.

#### Pie chart

A pie chart shows each group as a slice of the whole, so you can instantly see which categories take the biggest share of your budget.

Pie charts are best for **categories**. Since every expense belongs to exactly one category, the slices add up neatly to 100% and the proportions are meaningful. Grouping a pie chart by tags is possible but the percentages become misleading, because an expense tagged with two tags gets counted in two slices at once.

Clicking a slice takes you to the expense list filtered to that group (if the card is configured to do so).

See [Pie Chart Cards](cards/pie-chart.md) for configuration options.

#### Line chart

A line chart plots one or more data series over time. In month view each data point is one day; in year view each data point is one week.

Two modes are available: **cumulative** (`cum`) builds a running total up to each point, so the line never dips — useful for "total spent so far this month". **Base** (`base`) shows only the activity within each bucket, so you can see which days or weeks were most expensive.

Each series has its own query and aggregation method, so you can overlay "money spent" and "net balance" on the same chart.

See [Line Chart Cards](cards/line-chart.md) for configuration options.