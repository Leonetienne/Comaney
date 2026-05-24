# Account & Settings

To open your account settings, click your name or the profile menu in the top-right corner and choose **Profile / Settings**.

The page is divided into sections. Each section has its own **Save changes** button; changes in one section do not affect the others.

---

## Profile picture

Your profile picture appears in the header and next to your name throughout the app. If you have not uploaded one, Comaney shows your initials instead.

- Click **Choose image** to pick a file from your device. A cropping tool opens so you can frame the image before it is saved.
- Accepted formats: JPEG, PNG, GIF, WebP. Maximum file size: 5 MB.
- To remove your current picture, click **Remove**. Your initials will be shown again.

---

## Custom backdrop

A custom backdrop is a decorative image that sits behind the main content area and stays fixed while you scroll. It is purely visual and does not affect how Comaney works.

### Uploading a backdrop

Click **Choose image** and select a file. The image is uploaded and applied immediately.

- Accepted formats: PNG, JPEG, WebP, GIF. Maximum file size: 20 MB.
- To remove the backdrop entirely, click **Remove**.

### Backdrop settings

Once a backdrop is uploaded, a settings panel appears with the following options. Click **Save changes** to apply them.

| Setting | What it does |
|---|---|
| **Mode** | Controls how the image fills the background. **Cover** stretches the image to fill the whole area (some edges may be cropped). **Fit** shows the whole image without cropping (there may be empty space on the sides). |
| **Opacity** | A slider from 0 to 100. Lower values make the image more transparent so it blends into the background. 100 means fully visible. |
| **Extra backdrop styles** | An optional text box for CSS property declarations (no selectors, just properties and values). These are applied directly to the backdrop image on all screen sizes. |
| **Extra mobile backdrop styles** | The same as above, but only applied on screens up to 768 px wide. Use this to adjust the backdrop for phones and small tablets separately. |

### Using the extra style boxes

You can type standard CSS properties into these boxes to fine-tune how the backdrop looks. You do not need to be a developer to use simple values, but if you are not sure, leaving these boxes empty is perfectly fine.

**Example uses:**

```
filter: blur(4px);
```
Softens the image so it is less distracting behind the content.

```
transform: scale(1.05);
```
Zooms the image in slightly to avoid a thin gap at the edges when blur is applied.

```
object-position: center top;
```
In the mobile box: shifts the focal point of the image towards the top on small screens.

Changes in these boxes are previewed live in the page as you type, so you can see the effect before saving.

---

## Personal info

| Setting | What it does |
|---|---|
| **First name / Last name** | Your display name, shown in the header and in emails. |
| **Currency** | The symbol shown next to amounts throughout the app (for example: €, $, £). This is cosmetic only; Comaney does not convert between currencies. Default is €. |
| **Month starts on day** | The day of the month when your financial month begins. Default: 1. |
| **In the previous calendar month** | Turn this on if your pay arrives near the end of the month. For example, if your month starts on the 27th with this option on, your April would run from 27 March to 26 April. |
| **At month end, unspent allowance should** | What happens to any leftover budget at the end of a financial month. See [End-of-month rollover](#end-of-month-rollover) below. |

A small preview under the month settings shows you the exact date ranges your financial months will cover, so you can check the result before saving.

### Financial month example

Say your salary arrives on the 27th of each month. Set **Month starts on day** to 27 and turn on **In the previous calendar month**. Your months then look like this:

- **April** runs from 27 March to 26 April.
- **May** runs from 27 April to 26 May.

Everything you spend between paydays is grouped in the same month.

### End-of-month rollover

| Option | What happens |
|---|---|
| **be dropped** | Each month starts fresh. This is the right choice for most people. |
| **be deposited as savings** | Comaney automatically adds a savings deposit for the leftover amount. |
| **carry over to next month** | Comaney adds an income entry in the next month for the leftover amount so it shows up in next month's budget. |

---

## Email notifications

The top checkbox, **Enable email notifications**, is the master switch. When it is off, no notification emails are sent at all.

When the master switch is on, you can turn individual notification types on or off independently:

| Notification                                               | When it is sent |
|------------------------------------------------------------|---|
| **Expense due date reminders (upcoming and overdue)**      | A reminder before or after the due date of an expense that has reminders enabled. |
| **Expense marked as paid**                                 | When someone marks one of your expenses as paid. |
| **Added to, updated in, or removed from a shared expense** | When you are added, changed, or removed as a participant on a shared expense. |
| **A shared expense was assigned to you as upfront payer**  | When someone sets you as the person who paid upfront for a shared expense. |
| **A participant approved or rejected your shared expense** | When a participant confirms or declines their share of an expense you created. |
| **Settlement requests and confirmations**                  | When a settlement is proposed or confirmed in a shared project. |
| **Project membership changes**                             | When someone joins or leaves a project you are part of. |
| **Catalog Partnership events affecting you**               | When you receive a partnership invite, your invite is accepted or declined, or you are removed from a partnership. |
| **Catalog Partnership events affecting others**            | When a partner joins, leaves, or is removed from your Catalog Partnership. |

Invite emails are always sent, regardless of these settings.

---

## AI

These settings control the [AI Express Creation](ai-express-creation.md) feature.

| Setting | What it does |
|---|---|
| **Anthropic API key** | Your personal API key from Anthropic. If you add one, the AI feature uses your key with no usage limit in Comaney (Anthropic's own billing still applies). The key is stored securely and only the last four characters are shown after saving. |
| **Custom instructions** | Text passed to the AI before it processes your receipt or description. Use it to set rules for how expenses should be categorised or tagged. |

**Example custom instructions:**

```
When I shop at REWE, use the category "Groceries" and add the tag "REWE".
Group individual grocery items into a single expense unless they belong to different categories.
```

---

## Two-factor authentication

Your current status (on or off) is shown here, with a link to set it up or turn it off. See [Two-Factor Authentication](two-factor-auth.md) for the full guide.

---

## Email address

Your current email address is shown at the top of this section. To change it:

1. Enter the new address in the **New email address** field.
2. Enter your current password to confirm the change.
3. Click **Update email**.

Comaney sends a confirmation link to the new address. The change only takes effect after you click that link. Until then, your old address remains active and a "pending confirmation" notice is shown.

---

## Password

To change your password, enter your current password and then your new password twice. Click **Update password** to save.

---

## API key

An API key lets other apps or scripts access your Comaney account without logging in. See [REST API Access](api-access.md) for full details.

- If you have no key yet, click **Generate API key** to create one.
- Once generated, the key is shown in a text box. Click the copy icon to copy it to your clipboard.
- **Regenerate** replaces the current key with a new one. Any app using the old key will stop working until you update it there.
- **Revoke** deletes the key entirely and disables API access.

---

## Export data

Click **Export as ZIP** to download a ZIP archive containing CSV files with all your expenses, recurring expenses, categories, and tags. This is useful as a backup or for analysis in a spreadsheet.

---

## Danger zone

Click **Delete account** to permanently remove your account and all data associated with it. This cannot be undone. You will be taken to a confirmation page before anything is deleted.
