# Search & Filters

The search bar on the expense list and the filter field inside dashboard card settings both use the same simple filter language. Once you learn it, you can use it in both places.

All searches are case-insensitive: `type=Expense` and `type=expense` mean the same thing.

## Just type to search

The simplest thing you can do is type a word. Comaney looks for that word in the title, payee, note, and personal notes of every expense, as well as participant and project names.

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

## Filter by whether it is a recurring instance

```
recurring=yes
recurring=no
```

`recurring=yes` shows only expenses that were generated from a recurring expense. `recurring=no` shows only expenses that were entered manually.

`true`/`false` and `1`/`0` also work as alternatives to `yes`/`no`.

The **Hide recurring** checkbox on the expense list is a shortcut for this filter.

## Filter by shared expenses

```
shared=yes
shared=no
```

`shared=yes` shows only expenses that have at least one shared participant. `shared=no` shows only expenses with no participants — purely personal entries.

`true`/`false` and `1`/`0` also work as alternatives to `yes`/`no`.

## Filter by participant

```
participant=Alice
participant=me
```

Matches expenses where the given person appears as either the expense owner or a participant.

- A name or phrase is matched partially and case-insensitively against first name, last name, email address, and display name. `participant=ali` would find "Alice".
- `participant=me` matches only expenses where you are involved — either as the owner or as a participant.

## Filter by payer

```
payer=Alice
payer=me
```

Matches the person who paid the expense — the owning user, an offline buddy who paid upfront, or any offline buddy participant.

- `payer=me` shows only expenses you paid.
- `!payer=me` shows only expenses someone else paid (useful in Shared mode to see what others paid that you are a participant of).
- A name or phrase does a partial, case-insensitive match against first name, last name, email address, and offline buddy display name.

## Filter by project

```
project=Holiday
project=none
project=yes
project=no
```

- `project=<name>` — expenses linked to a project whose name contains the phrase (partial match, case-insensitive).
- `project=none` or `project=no` — expenses with no project assigned.
- `project=yes` — expenses that belong to any project.

`true`/`false` and `1`/`0` also work as alternatives to `yes`/`no`.

## Filter by category

```
cat=Groceries
```

Finds expenses whose category name contains "Groceries" (partial match, so `cat=Groc` also works). This includes your personal category override if you have set one for a shared expense.

```
cat=none
```

Finds expenses with no category — neither a direct category on the expense nor a personal override.

## Filter by tag

```
tag=amazon
```

Finds expenses with any tag that contains "amazon". This includes your personal tags if you have added them to a shared expense.

```
tag=none
```

Finds expenses with no tags at all — neither direct tags nor personal ones.

## Filter by payee

```
payee=Amazon
```

Partial match against the payee field.

```
payee=none
```

Finds expenses with no payee set.

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
| `shared=yes payer=me` | Your expenses that have participants |
| `!payer=me participant=me` | Expenses someone else paid that you are part of |
| `project=none type=expense` | Personal expenses not linked to any project |
