# Account & Settings

To open your account settings, click your name or the profile menu in the top-right corner and choose **Profile / Settings**.

## Your personal details

| Setting | What it does |
|---|---|
| **First name / Last name** | Your display name, shown in the header and in emails. |
| **Email** | Your login email address. If you change it, Comaney sends a confirmation link to the new address; the change only takes effect after you click that link. |
| **Password** | Change your login password. You will need to enter your current password first. |
| **Currency** | The symbol shown next to amounts throughout the app (for example: €, $, £). This is cosmetic only; Comaney does not convert between currencies. Default is €. |

## Financial month settings

By default, Comaney's months follow the calendar: January is 1 January to 31 January, February is 1 February to 28/29 February, and so on.

If your pay arrives mid-month, you can shift the start of your "financial month" to match your pay cycle. That way, all the spending between one payday and the next is grouped together.

| Setting | What it does |
|---|---|
| **Month start day** | The day of the month when your financial month begins. Default: 1. |
| **Month start is in the previous calendar month** | Turn this on if your pay arrives near the end of the month and you want, for example, your "March" budget to start on 27 February. |

### An example

Say your salary lands on the 27th of each month. You would set:

- **Month start day**: 27
- **Month start is in the previous calendar month**: on

Then your financial months look like this:

- **April** runs from 27 March to 26 April.
- **May** runs from 27 April to 26 May.

Everything you spend between paydays is in the same month.

## End-of-month rollover

This setting controls what happens to any money left in your budget at the end of a financial month.

| Option | What happens |
|---|---|
| **Do nothing** | Each month starts fresh. This is the right choice for most people. |
| **Deposit to savings** | Comaney automatically adds a savings deposit for the leftover amount, recording that the surplus has been moved into savings. |
| **Carry over** | Comaney adds an income entry in the next month for the leftover amount, so it shows up in next month's budget. |

## AI settings

These settings are for the [AI Express Creation](ai-express-creation.md) feature.

| Setting | What it does |
|---|---|
| **Anthropic API key** | Your personal API key from Anthropic. If you add this, the AI feature uses your key exclusively, with no usage limits in Comaney (Anthropic's own billing still applies). |
| **AI custom instructions** | Text you add here is passed to the AI before it processes your receipt or description. Use it to tell the AI your preferred categories, tags, or any rules you want it to follow. |

**Example custom instructions:**
```
When I shop at REWE, use the category "Groceries" and add the tag "REWE".
Group individual grocery items into a single expense unless they belong to different categories.
```

## Email notifications

| Setting | What it does |
|---|---|
| **Email notifications** | The master switch for all reminder emails. When turned off, no reminders are sent for any expense, even if individual expenses have notifications enabled. |

## Two-factor authentication

See [Two-Factor Authentication](two-factor-auth.md) for the full guide. Your current status (on or off) is shown on this settings page, with a link to set it up or disable it.

## API key

See [REST API Access](api-access.md). From this page you can generate or revoke the key that allows other apps to connect to your Comaney account.

## Account actions

### Export your data

Click **Export account data** to download a complete copy of your account: all expenses, scheduled expenses, categories, and tags. This is useful as a backup, or if you want to analyse your data in a spreadsheet.

### Delete your account

Click **Delete account** to permanently remove your account and everything in it. This cannot be undone. You will be asked to confirm your password before the deletion goes through.
