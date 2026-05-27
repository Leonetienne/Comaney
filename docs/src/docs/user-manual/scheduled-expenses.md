# Recurring Expenses

A recurring expense is a bill or payment that repeats on a regular pattern: monthly rent, a weekly grocery budget, an annual insurance premium, and so on.

Instead of adding the same expense manually every month, you set it up once and Comaney creates the individual records for you automatically.

## How it works

You create a template with all the details of the recurring payment. Comaney then generates real expense records from that template according to your chosen schedule. Each generated record behaves exactly like a normal expense: you can edit it, settle it, or add a note to it without affecting the template or any other instances.

## Setting up a recurring expense

Go to **Recurring Expenses** in the navigation and click **New scheduled expense**.

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

## Changing the repeat pattern or time window

Comaney only generates each recurring expense's records once per financial year, so editing the repeat pattern (**Repeat every**) or the time window (**Repeat base date**, **End on**) after creation needs special care: it can affect records that were already generated.

For this reason, those fields are locked when editing an existing recurring expense. To change them:

1. Tick **Modify schedule** (for the repeat pattern) or **Modify schedule time window** (for the base date / end date).
2. Confirm the warning that appears. It explains what will happen:
    - Changing the **repeat pattern** deletes and re-creates every record generated for the current financial year, including ones you already settled.
    - Changing the **time window** only adjusts the edges: records that now fall outside the window are deleted (even if settled), and any newly-in-range dates are generated. Records inside the window are left untouched.
3. Edit the fields and save.

If you don't tick the checkbox, those fields stay as they were, even if you try to change them.

## Pausing a recurring expense

If you want to stop new records from being generated temporarily, open the recurring expense and click **Deactivate**. Existing records that have already been created are not affected. You can reactivate the template at any time to resume generation.

## Updating already-generated expenses

Changing the template (for example raising the value after a pay rise) does not change records that were already generated; that keeps your past history intact. To apply the new details to existing records, open the recurring expense and click **Update expenses**. A list of records generated for the current financial year is shown, with each one selected by default.

- **Select all** / **Deselect all** check or uncheck every record.
- **Select unsettled** checks only the records you have not settled yet, so you can apply a change without touching ones already paid.

Untick anything you want to leave as-is, then confirm to apply the template's current details to the selected records.

## Making a copy

Open a recurring expense and click **Clone** to create an identical template. The copy gets "CLONE" added to the title. This is useful when you want a similar schedule with slightly different details.

## The recurring expense list

Click **Recurring Expenses** in the navigation to see all your templates. This list is not tied to a specific month; all templates are always shown, with their next due date and repeat schedule displayed.

!!! tip
    Recurring expenses are a great fit for any fixed cost that recurs on a known date: rent, loan repayments, streaming subscriptions, insurance premiums, and gym memberships.
