# Expenses

An expense is any money movement you want to track: something you paid, money you received, or a transfer to savings. Every record you add in Comaney is an expense.

## Types of transactions

When you add a new expense, you choose what kind it is:

| Type | What it means |
|---|---|
| **Expense** | Money you spend. For example: rent, groceries, a cinema ticket. |
| **Income** | Money you receive. For example: your salary, a refund, a gift. |
| **Savings deposit** | Money you move into savings. Comaney treats this like spending because the money leaves your day-to-day budget. |
| **Savings withdrawal** | Money you take back from savings. Treated like income: it comes back into your budget. |
| **Carry-over** | Created automatically by Comaney at the end of a month when you have the carry-over setting turned on. You cannot create these yourself. |

## What information you can record

| Field | Do I have to fill this in? | What it's for |
|---|---|---|
| **Title** | Yes | A short name for the record. For example: "Rent", "Grocery shop", "January salary". |
| **Type** | Yes | The transaction type (see above). |
| **Value** | Yes | The amount of money. Always enter a positive number; Comaney handles the sign automatically based on the type. |
| **Due date** | No | When the payment is or was expected. Used for sorting and for sending reminder emails. |
| **Payee** | No | Who you paid, or who paid you. For example: "REWE", "Employer". |
| **Category** | No | A broad group for the expense. You can only pick one. For example: "Groceries" or "Housing". |
| **Tags** | No | Extra labels. You can add as many as you like. For example: "Credit card", "Amazon". |
| **Note** | No | Any extra detail you want to remember. |
| **Settled** | | Tick this if the money has actually changed hands. Leave it unticked for upcoming obligations you haven't paid yet. |
| **Auto-settle on due date** | No | When turned on, Comaney automatically marks the expense as settled when the due date arrives. |
| **Notify** | No | When turned on, Comaney sends you reminder emails before the due date. Only works if the expense has a due date and you have email notifications enabled in your account settings. |

## Adding a new expense

1. Click **Expenses** in the navigation, then click **New expense**.
2. Fill in the title, choose the type, and enter the value.
3. Fill in any other fields you want to track.
4. Click **Save**.

The new record appears in your expense list for the current period.

!!! tip "Got a receipt? Let the AI handle it."
    Instead of typing everything manually, you can take a photo of a receipt and let Comaney extract the details for you. See [AI Express Creation](ai-express-creation.md).

## Settling an expense

An unsettled expense means the money hasn't moved yet; it's something you owe or are expecting. Once the payment happens, mark it as settled.

You can settle an expense in three ways:

- Open the expense, tick the **Settled** checkbox, and click Save.
- Click the **Mark as settled** link in a reminder email.
- Turn on **Auto-settle on due date** when creating the expense, and Comaney will settle it for you on the day.

## Making a copy of an expense

If you need to record something similar to an existing expense, open it and click **Clone**. Comaney creates a copy with all the same details, with "CLONE" added to the title so you can tell them apart. Then edit the copy as needed.

## Removing an expense

You have two options:

- **Delete**: removes the record permanently. Use this if you added something by mistake.
- **Deactivate**: hides the expense from all totals and charts, but keeps the record in your history. Use this if an obligation was cancelled but you want to keep a note of it.

## The expense list

The expense list shows all your records for the current period. At the top you can switch between **month view** and **year view**, and use the arrows to move to a different month or year.

### Searching

The search bar at the top of the list lets you find expenses quickly. You can type any word to search by title, payee, or note. You can also use filters for more precise results; see [Search & Filters](dashboard/query-language.md) for the full guide.

**Simple examples:**

- Type `rent` to find anything with "rent" in the title, payee, or note.
- Type `settled=no` to see only unpaid expenses.
- Type `type=income` to see only income records.

### Bulk actions

To act on several expenses at once:

1. Tick the checkbox next to each expense you want to select.
2. Choose an action at the top: **Settle**, **Unsettle**, or **Delete**.

The total value of all selected expenses is shown at the bottom, which is handy for spot-checking a group.

## Muting reminders for one expense

If you no longer want email reminders for a specific expense, open it and click **Mute notifications**. You can also click the mute link inside any reminder email.

To turn off all reminder emails for your account at once, go to **Account Settings** and disable **Email notifications**.
