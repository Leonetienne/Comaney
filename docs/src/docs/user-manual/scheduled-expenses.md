# Scheduled Expenses

A scheduled expense is a recurring bill or payment that repeats on a regular pattern: monthly rent, a weekly grocery budget, an annual insurance premium, and so on.

Instead of adding the same expense manually every month, you set it up once and Comaney creates the individual records for you automatically.

## How it works

You create a template with all the details of the recurring payment. Comaney then generates real expense records from that template according to your chosen schedule. Each generated record behaves exactly like a normal expense: you can edit it, settle it, or add a note to it without affecting the template or any other instances.

## Setting up a scheduled expense

Go to **Scheduled Expenses** in the navigation and click **New scheduled expense**.

Fill in the same fields as a normal expense (title, type, value, payee, category, tags, note), plus the schedule:

| Field | What to enter |
|---|---|
| **Repeat base date** | The date of the first (or a typical) occurrence. All future dates are calculated from this anchor. |
| **Repeat every (number)** | How many units between each occurrence. Enter `1` for every month, `2` for every two weeks, etc. |
| **Repeat every (unit)** | Choose days, weeks, months, or years. |
| **End on** | Optional. If the subscription ends on a known date, enter it here. Leave blank for an open-ended schedule. |

### Examples

| What you want | Base date | Every | Unit |
|---|---|---|---|
| Monthly rent on the 1st | 01 Jan 2025 | 1 | months |
| Weekly grocery top-up on Fridays | 03 Jan 2025 | 1 | weeks |
| Quarterly insurance premium | 01 Jan 2025 | 3 | months |
| Annual membership fee | 15 Mar 2025 | 1 | years |

## Pausing a scheduled expense

If you want to stop new records from being generated temporarily, open the scheduled expense and click **Deactivate**. Existing records that have already been created are not affected. You can reactivate the template at any time to resume generation.

## Making a copy

Open a scheduled expense and click **Clone** to create an identical template. The copy gets "CLONE" added to the title. This is useful when you want a similar schedule with slightly different details.

## The scheduled expense list

Click **Scheduled Expenses** in the navigation to see all your templates. This list is not tied to a specific month; all templates are always shown, with their next due date and repeat schedule displayed.

!!! tip
    Scheduled expenses are a great fit for any fixed cost that recurs on a known date: rent, loan repayments, streaming subscriptions, insurance premiums, and gym memberships.
