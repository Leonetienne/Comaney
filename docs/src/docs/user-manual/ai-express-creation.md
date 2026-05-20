# AI Express Creation

Express creation lets you log expenses by describing them in plain language or taking a photo of a receipt. An AI reads what you provide and fills in all the expense details for you, ready for your review before anything is saved.

## How to use it

1. Click **AI** in the navigation, then click **Express creation**.
2. Either:
    - **Take a photo or upload an image** of a receipt, invoice, or any document with prices.
    - **Type a description** of what you bought. For example: "Bought groceries at REWE for 37.50 and a coffee for 4.20".
3. Click **Submit**.
4. Review the suggested expenses. You can change any field: title, type, value, payee, date, category, tags, or project assignment.
5. Click **Save** to add them.

Nothing is saved until you click Save. You are always in control.

## What the AI reads from a receipt

From a photo, the AI tries to extract:

- The shop name (as the payee)
- The date on the receipt
- Individual items or totals, grouped by category where possible
- Tags, if they match ones you have already set up

If several items on a receipt belong to the same category and would get the same tags, they are combined into one expense to keep things tidy.

## Getting better results with custom instructions

You can teach the AI your preferences so it categorises and labels things the way you like. Go to **Account Settings → AI custom instructions** and write a short note.

**Example:**
```
When I shop at REWE, use the category "Groceries" and the tag "REWE".
Use the payee "Amazon" for all Amazon purchases.
Combine grocery items into one expense unless they belong to different categories.
```

The AI will follow these instructions every time.

## Project assignment

If you have projects set up, the AI will suggest which project each expense belongs to, based on the project name and description. You can review and change the assignment in each card using the **Expense assignment** tabs:

- **None**: personal expense, not linked to any project.
- **Direct Buddy**: a direct one-on-one buddy payment.
- **Project**: assign to a shared project. For projects with multiple members, you can also set the upfront payer and split shares.

The AI will never assign a project without a strong reason.

## Privacy

Photos and descriptions you submit are sent to Anthropic's AI service for processing. Do not upload documents containing sensitive personal data such as identity card numbers or passport scans.

The data transmitted to Anthropic includes only your list of tags, categories, projects (names and descriptions), your custom instruction, your expense description and/or receipt picture.
Comaney will never transmit your existing transactions.

## AI Licensing

Express creation requires an Anthropic API key. There are two ways this can work:

### (Most likely your case) If your administrator has set up a shared trial key

A shared key may already be available. It has a small monthly budget per user (typically a few cents of API cost). Once your share is used up for the month, the feature becomes unavailable until the following month. The page will tell you if this is the case.

### Using your own key

If you have an Anthropic account, you can add your own API key in **Account Settings → Anthropic API key**. When your own key is set, it is used instead of the shared key, with no Comaney usage limits (Anthropic will bill you directly).
