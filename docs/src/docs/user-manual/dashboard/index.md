# Dashboard

The dashboard is a fully customisable grid of cards. Each card is a self-contained widget that computes and displays financial data for the currently selected period.

## Choosing a date range

The **date range bar** at the top of the dashboard controls which period all cards show data for. It has three parts:

**Quick presets** - buttons for common ranges:

| Button | What it shows |
|---|---|
| Fin.May / Fin.Jun / Fin.Jul | The previous, current, and next financial month. Financial months follow your start-day setting in Account Settings. |
| 2025 / 2026 / 2027 | The previous, current, and next calendar year (always 1 Jan – 31 Dec). |
| Q1 / Q2 / Q3 / Q4 | Calendar quarters: Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec. |
| Clear | Resets to the default range (your current financial month). |

**Manual dates** - the Start and End date pickers. Type or pick any two dates to define a custom range. All cards update immediately.

Your chosen range is remembered when you move between pages.

**Display mode** (dashboard only), the Personal / Shared toggle next to the date range.
In **Personal**, your own expenses are always calculated fully and others expenses are ignored. In a nutshell: "Money that leaves your pocket"-
In **Shared** mode, your own expenses are only calculated at your own share, and others expenses are included
respecting your share in them. In a nutshell: "Depts you have agreed to take between friends", as in "I pay for the hotel, you pay for dinner".
In personal mode, it would only show the cost for the hotel, but that it does completely. In shared mode, it shows your share of the hotel cost and your share of the dinner cost.
Use shared mode if you want to see what **tags** and **categories** you took loans for by lets say your room mate. 

## Multiple dashboards

You can have as many dashboards as you like, each with its own set of cards. Dashboards appear as tabs along the top of the page (or a dropdown on mobile).

### Adding a dashboard

Click the **+** button at the right end of the tab bar, type a name in the field that appears, and press Enter or click **Add**.

### Switching dashboards

Click any tab to switch to that dashboard. On mobile, tap the selector at the top to open the list and choose a dashboard.

### Renaming a dashboard

Double-click a tab to edit its name inline. Press Enter or click away to save.

### Reordering dashboards

Drag a tab left or right to change its position.

### Deleting a dashboard

Click the **x** that appears on the active tab. The last remaining dashboard cannot be deleted.

### Moving a card to another dashboard

Open the card editor (pencil icon) and use the **Move to dashboard** dropdown to place the card on a different dashboard.

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