# Search & Filters

The search bar on the expense list and the filter field inside dashboard card settings both use the same simple filter language. Once you learn it, you can use it in both places.

All searches are case-insensitive: `type=Expense` and `type=expense` mean the same thing.

## Just type to search

The simplest thing you can do is type a word. Comaney looks for that word in the title, payee, and note of every expense.

| What you type | What it finds |
|---|---|
| `rent` | Any expense where the title, payee, or note contains "rent" |
| `"whole foods"` | Any expense containing the exact phrase "whole foods" |

## Filter by type

```
type=expense
type=income
type="savings deposit"
type="savings withdrawal"
```

Use quotes around values that contain a space.

## Filter by payment status

```
settled=yes
settled=no
```

`true`/`false` and `1`/`0` also work as alternatives to `yes`/`no`.

## Filter by category

```
cat=Groceries
```

Finds expenses whose category name contains "Groceries" (partial match, so `cat=Groc` would also work).

```
cat=none
```

Finds expenses with no category at all.

## Filter by tag

```
tag=amazon
```

Finds expenses with any tag that contains "amazon".

```
tag=none
```

Finds expenses with no tags at all.

## Filter by payee

```
payee=Amazon
```

Partial match against the payee field.

## Filter by amount

You can compare the value of an expense:

| Example | What it finds |
|---|---|
| `value>100` | Expenses over 100 |
| `value<=50` | Expenses of 50 or less |
| `value=77.50` | Expenses of exactly 77.50 |

## Filter by date

You can filter by the due date using three different date formats:

| Format | Example |
|---|---|
| Day.Month.Year | `date>=31.01.2025` |
| Month/Day/Year | `date>=01/31/2025` |
| Year-Month-Day | `date>=2025-01-31` |

Instead of a specific date, you can use one of these special words:

| Word | Resolves to |
|---|---|
| `today` | Today's date |
| `cur_week_start` | Monday of the current week |
| `cur_week_end` | Sunday of the current week |

Examples:

```
date<=today
```

All expenses due on or before today.

```
date>=cur_week_start date<=cur_week_end
```

All expenses due somewhere within the current week.

## Combining filters

Separate any two filters with a space to require both. This is AND logic: both conditions must be true.

```
type=expense settled=no
```

Unsettled expenses only.

```
cat=Groceries value>50
```

Grocery expenses over 50.

## OR: either one or the other

Use `||` between two filters when either should be enough:

```
type=income || type="savings withdrawal"
```

Income records or savings withdrawals.

## NOT: exclude something

Put `!` in front of a filter or word to exclude it:

```
type=expense !rent
```

All expenses that do not mention "rent".

```
!tag=amazon
```

Expenses with no amazon tag.

## Grouping with brackets

Use brackets to group parts of a query when combining AND and OR:

```
(type=expense settled=yes) || type=income
```

Settled expenses, plus all income records.

## Quick examples

| Query | What it finds |
|---|---|
| `settled=no value>500` | Unpaid expenses over 500 |
| `date>=01.01.2025` | Due on or after 1 January 2025 |
| `cat=Food payee=REWE` | REWE expenses in a food category |
| `tag="credit card" settled=no` | Unpaid credit-card expenses |
| `type=expense !rent` | Expenses with no mention of rent |
| `type=income \|\| settled=yes` | All income, or anything already paid |
