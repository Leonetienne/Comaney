# AI Express Creation

Express creation lets you log expenses by describing them in plain language or taking a photo of a receipt. An AI reads what you provide and fills in all the expense details for you, ready for your review before anything is saved.

## How to use it

1. Click **Add Expense** in the navigation, then choose **Create with AI**. Or, from the **Expenses** page or a project page, click the **+** button and choose **AI Express**; from a project page this also pre-fills the description with a prompt to create all of that project's expenses, which you can edit before submitting.
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

## Project and buddy assignment

If you have projects or buddies set up, the AI will suggest how each expense should be shared, based on your description and the project or buddy names. You can review and change the assignment in each card using the **Expense assignment** tabs:

- **None**: personal expense, not shared with anyone.
- **Direct Buddy**: a one-on-one split with a single buddy.
- **Project**: assign to a shared project. For projects with multiple members, you can also set the upfront payer and split shares.

The AI will never share an expense without a strong reason.

### Sharing one-on-one with a buddy

If you mention splitting something with one person, the AI can set up a direct buddy expense for you. For example, "Split the taxi with Kevin, 20 in total" shares it evenly with Kevin. You can also tell the AI who paid and how to split it:

- **Say who paid.** "Kevin paid for our lunch, 30, I owe him half" records Kevin as the one who paid upfront. If you don't say, the app assumes you paid.
- **Set the split.** "Dinner was 40, but only 10 of it was Kevin's" gives Kevin a smaller share. Without a hint, it's split evenly.

### Telling the AI who shares a project expense

When an expense belongs to a project, everyone in that project shares the cost equally by default. You can tell the AI about exceptions right in your description, and it will set them up for you to review:

- **Leave someone out.** "We ordered takeout for the summer vacation trip, but Robbie doesn't join in" leaves Robbie out of the split; the others share equally.
- **Give someone a set share.** "Dinner for the trip, but Robbie is on us, put him at 0%" keeps Robbie on the expense at 0%, and the rest split what's left.
- **Say who paid.** "Robbie paid for the group dinner on the trip" sets Robbie as the person who paid upfront; everyone else shares what they owe. If you don't mention anyone, the app assumes you paid.

You can always adjust who paid, who shares, and by how much before saving.

## Privacy

Photos and descriptions you submit are sent to Anthropic's AI service for processing. Do not upload documents containing sensitive personal data such as identity card numbers or passport scans.

The data transmitted to Anthropic includes only your list of tags, categories, projects (names, descriptions, and the names of their members), the names of your buddies, your custom instruction, your expense description and/or receipt picture.
Comaney will never transmit your existing transactions.

## AI Licensing

Express creation requires an Anthropic API key. There are two ways this can work:

### (Most likely your case) If your administrator has set up a shared trial key

A shared key may already be available. It has a small monthly budget per user (typically a few cents of API cost). Once your share is used up for the month, the feature becomes unavailable until the following month. The page will tell you if this is the case.

### Using your own key

If you have an Anthropic account, you can add your own API key in **Account Settings → Anthropic API key**. When your own key is set, it is used instead of the shared key, with no Comaney usage limits (Anthropic will bill you directly).
