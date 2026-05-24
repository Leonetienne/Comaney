# Data Export

Comaney lets you download your expense data so you can open it in a spreadsheet, keep a backup, or share it with someone.

## Download as a spreadsheet (CSV)

A CSV file opens in Excel, Google Sheets, LibreOffice Calc, or any other spreadsheet app.

1. Go to **Expenses** and select the period you want (a specific month, or a full year in year view).
2. Click **Export → Download CSV**.

The file includes all expenses visible in the list at that moment. If you have a search filter active, only the filtered results are included.

### What columns are included

| Column | What it contains |
|---|---|
| Date due | The due date, in the format YYYY-MM-DD. Blank if no due date was set. |
| Title | The expense title. |
| Type | The transaction type: expense, income, savings_dep, or savings_wit. |
| Value | The amount (always a positive number). |
| Payee | Who was paid, or who paid you. Blank if not set. |
| Category | The category name. Blank if uncategorised. |
| Tags | All tags, separated by a pipe character. Blank if no tags. |
| Note | Any note text. |
| Settled | True or False. |

## Download all your data

For a complete backup of everything in your account, go to **Account Settings** and click **Export account data**. This downloads a ZIP file containing multiple CSV files:

- Your account details (email, settings, currency, and so on)
- All expenses from all periods, not just the current one
- All scheduled expense templates
- All categories and tags
- All dashboard cards

!!! note
    Your Anthropic API key is redacted in the export for security.

This format is useful if you want to move your data to another system or keep a full archive. If you just need a spreadsheet for a single month, the expense csv export is simpler.
