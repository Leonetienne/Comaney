# REST API Access

The REST API lets other apps or scripts read and write your Comaney data automatically, without you clicking through the website. For example, you could write a script that imports bank transactions, or connect Comaney to a home automation tool.

This page is for more technical users. To let an AI assistant work with your account, see [AI Assistants (MCP)](ai-assistants.md). If you just want to export data, see [Data Export](data-export.md).

Everything the API does behaves exactly like the website: sharing an expense notifies the people involved, editing its amount resets their approvals, and new categories reach your Catalog Partnership.

## Generating an API key

1. Go to **Settings → Advanced → API key**.
2. Click **Generate API key**.
3. Copy the key.

To revoke a key, click **Revoke**. Any app using the old key stops working immediately.

## Restricting the API key

A new key may do everything. Click **Restrict** next to the key to choose, per area, whether apps using it may only **read** or also **write** (change, create, delete). Write always includes read. The areas are the same as for [AI assistants](ai-assistants.md#restricting-what-an-assistant-may-do) and match the sections below. A request the key may not make is answered with `403` and changes nothing. Revoking the key and generating a new one keeps its permissions.

## How to authenticate

Include your API key in every request, in the `Authorization` header:

```
Authorization: Bearer your_api_key_here
```

Requests and responses are JSON. All paths start with `/api/v2/`.

## Expenses

| Action | Method | Path |
|---|---|---|
| List expenses | GET | `/api/v2/expenses/` |
| Sum expenses, optionally grouped | GET | `/api/v2/expenses/totals/` |
| Get one expense | GET | `/api/v2/expenses/<id>/` |
| Add an expense | POST | `/api/v2/expenses/` |
| Update an expense | PATCH | `/api/v2/expenses/<id>/` |
| Delete an expense | DELETE | `/api/v2/expenses/<id>/` |
| Clone an expense | POST | `/api/v2/expenses/<id>/clone/` |
| Get your own category, tags and note on a shared expense | GET | `/api/v2/expenses/<id>/overlay/` |
| Set your own category, tags and note on a shared expense | PUT | `/api/v2/expenses/<id>/overlay/` |
| Settle, tag, categorise or delete many expenses | POST | `/api/v2/expenses/bulk/` |

Listing and summing take these parameters:

| Parameter | What it does |
|---|---|
| `date_from`, `date_to` | Date range in `YYYY-MM-DD` format. Both or neither. |
| `year`, `month` | Financial year and month (default: current). Used without a date range. |
| `view` | `year` for the whole financial year. |
| `q` | A filter in the [query language](dashboard/query-language.md). |
| `sharing` | `shared` includes expenses others share with you, counted at your share. |
| `type`, `group_by` | Totals only: transaction type to sum (default `expense`) and grouping: `category`, `tag`, `payee` or `month`. |

To share an expense, send an `assignment`:

```json
{
  "mode": "project",
  "project_id": 12,
  "payer": {"type": "me"},
  "participants": [{"type": "feuser", "id": 34, "share_percent": 50}]
}
```

`mode` is `contact` (exactly one participant) or `project`. Payers and participants are `feuser` (a person with an account) or `offline` (an offline contact or member). `"assignment": null` makes an expense personal again; leaving it out keeps the sharing as it is.

Deleting in bulk takes two calls: the first returns what would be deleted and a `confirm_token`; repeating the call with that token within 10 minutes deletes exactly those expenses.

## Recurring expenses

| Action | Method | Path |
|---|---|---|
| List templates | GET | `/api/v2/scheduled/` |
| Create a template | POST | `/api/v2/scheduled/` |
| Get one template | GET | `/api/v2/scheduled/<id>/` |
| Update a template | PATCH | `/api/v2/scheduled/<id>/` |
| Delete a template | DELETE | `/api/v2/scheduled/<id>/` |
| Clone a template | POST | `/api/v2/scheduled/<id>/clone/` |
| List this year's generated expenses | GET | `/api/v2/scheduled/<id>/expenses/` |
| Apply the template to generated expenses | POST | `/api/v2/scheduled/<id>/apply/` |

Changing how often a template repeats (`repeat_every_factor`, `repeat_every_unit`) or the time window it covers (`repeat_base_date`, `end_on`) reshapes a year's worth of generated expenses, so those changes only take effect with a confirmation flag in the same request: `confirm_modify_schedule: true` for the repeat pattern, `confirm_modify_schedule_window: true` for the time window. Without the flag, those fields stay unchanged and every other field still updates.

## Categories and tags

| Action | Method | Path |
|---|---|---|
| List categories | GET | `/api/v2/categories/` |
| Create a category | POST | `/api/v2/categories/` |
| Get one category | GET | `/api/v2/categories/<id>/` |
| Rename a category | PATCH | `/api/v2/categories/<id>/` |
| Delete a category | DELETE | `/api/v2/categories/<id>/` |
| List tags | GET | `/api/v2/tags/` |
| Create a tag | POST | `/api/v2/tags/` |
| Get one tag | GET | `/api/v2/tags/<id>/` |
| Rename a tag | PATCH | `/api/v2/tags/<id>/` |
| Delete a tag | DELETE | `/api/v2/tags/<id>/` |

## Dashboard

| Action | Method | Path |
|---|---|---|
| Month summary | GET | `/api/v2/dashboard/` |
| List dashboards | GET | `/api/v2/dashboards/` |
| Create a dashboard | POST | `/api/v2/dashboards/` |
| Rename a dashboard | PATCH | `/api/v2/dashboards/<id>/` |
| Delete a dashboard | DELETE | `/api/v2/dashboards/<id>/` |
| List cards with their data | GET | `/api/v2/cards/` |
| Card YAML reference | GET | `/api/v2/cards/reference/` |
| Add a card | POST | `/api/v2/cards/` |
| Change a card | PATCH | `/api/v2/cards/<id>/` |
| Delete a card | DELETE | `/api/v2/cards/<id>/` |

## Projects

| Action | Method | Path |
|---|---|---|
| List projects | GET | `/api/v2/projects/` |
| Get a project with members and balances | GET | `/api/v2/projects/<id>/` |
| Whole project: every expense with shares, balances between all members | GET | `/api/v2/projects/<id>/overview/` |
| Create a project | POST | `/api/v2/projects/` |
| Change a project | PATCH | `/api/v2/projects/<id>/` |
| Delete a project (send `confirm_name`) | DELETE | `/api/v2/projects/<id>/` |
| Invite someone | POST | `/api/v2/projects/<id>/invites/` |
| Withdraw an invitation | DELETE | `/api/v2/projects/<id>/invites/<invite_id>/` |
| Accept or decline an invitation | POST | `/api/v2/projects/invites/<invite_id>/respond/` |
| Add an offline member | POST | `/api/v2/projects/<id>/offline-members/` |
| Rename an offline member | PATCH | `/api/v2/projects/<id>/offline-members/<member_id>/` |
| Remove a member | DELETE | `/api/v2/projects/<id>/members/<member_id>/` |
| Transfer admin rights | POST | `/api/v2/projects/<id>/transfer-admin/` |
| Leave a project | POST | `/api/v2/projects/<id>/leave/` |
| Unlink an expense | POST | `/api/v2/projects/<id>/expenses/<expense_id>/unlink/` |
| Delete a project expense | DELETE | `/api/v2/projects/<id>/expenses/<expense_id>/` |
| Clear all debts at once | POST | `/api/v2/projects/<id>/settle-all/` |

## Contacts

| Action | Method | Path |
|---|---|---|
| List contacts with balances | GET | `/api/v2/contacts/` |
| Invite someone | POST | `/api/v2/contacts/invites/` |
| Withdraw an invitation | DELETE | `/api/v2/contacts/invites/<id>/` |
| Accept or decline an invitation | POST | `/api/v2/contacts/invites/<id>/respond/` |
| Remove a contact | DELETE | `/api/v2/contacts/<link_id>/` |
| Turn auto-accept on or off | PUT | `/api/v2/contacts/<link_id>/auto-accept/` |
| Add an offline contact | POST | `/api/v2/contacts/offline/` |
| Rename an offline contact | PATCH | `/api/v2/contacts/offline/<id>/` |
| Remove an offline contact | DELETE | `/api/v2/contacts/offline/<id>/` |

## Approvals and settlements

| Action | Method | Path |
|---|---|---|
| Everything waiting for your decision | GET | `/api/v2/pending/` |
| Approve or reject a pending item | POST | `/api/v2/pending/decide/` |
| List recorded settlements | GET | `/api/v2/settlements/` |
| Record a settlement | POST | `/api/v2/settlements/` |

## Catalog Partnership

| Action | Method | Path |
|---|---|---|
| Your partnership | GET | `/api/v2/partnership/` |
| Invite a partner | POST | `/api/v2/partnership/invites/` |
| Withdraw an invitation | DELETE | `/api/v2/partnership/invites/<id>/` |
| Remove a partner | DELETE | `/api/v2/partnership/partners/<feuser_id>/` |
| Leave the partnership | POST | `/api/v2/partnership/leave/` |
| Joining: your catalog next to the inviter's | GET | `/api/v2/partnership/onboarding/` |
| Joining: preview the mapping | POST | `/api/v2/partnership/onboarding/preview/` |
| Joining: apply the previewed mapping | POST | `/api/v2/partnership/onboarding/apply/` |
| Decline an invitation | POST | `/api/v2/partnership/onboarding/decline/` |

## Account settings

| Action | Method | Path |
|---|---|---|
| Get your settings | GET | `/api/v2/account/` |
| Change your settings | PATCH | `/api/v2/account/` |

Your email address, password, two-factor authentication and keys cannot be changed through the API.

## A quick example

This command (for the terminal) creates a new expense:

```bash
curl -X POST https://your-comaney-address/api/v2/expenses/ \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Coffee",
    "type": "expense",
    "value": "4.20",
    "payee": "Starbucks",
    "date_due": "2025-03-20",
    "settled": true
  }'
```

## Error responses

If something goes wrong, the API returns a JSON message explaining the error, for example:

```json
{"error": "'value' must be a valid decimal number."}
```

Common response codes: `200` (success), `201` (created), `204` (deleted), `400` (bad request), `401` (wrong or missing API key), `403` (not allowed), `404` (not found).

See more examples in the [Postman collection](https://github.com/Leonetienne/Comaney/blob/master/api/Comaney_API.postman_collection.json).
