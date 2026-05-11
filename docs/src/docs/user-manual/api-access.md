# REST API Access

The REST API lets other apps or scripts read and write your Comaney data automatically, without you clicking through the website. For example, you could write a script that imports bank transactions, or connect Comaney to a home automation tool.

This page is for more technical users. If you just want to export data, see [Data Export](data-export.md) instead.

## Generating an API key

1. Go to **Account Settings → API key**.
2. Click **Generate key**.
3. Copy the key.

To revoke a key, click **Revoke key**. Any app using the old key will immediately stop working.

## How to authenticate

Include your API key in every request, in the `Authorization` header:

```
Authorization: Bearer your_api_key_here
```

## Available endpoints

All endpoints start with `/api/v1/`.

### Expenses

| Action | Method | Path |
|---|---|---|
| List expenses for a period | GET | `/api/v1/expenses/` |
| Add a new expense | POST | `/api/v1/expenses/` |
| Get one expense | GET | `/api/v1/expenses/<id>/` |
| Update an expense | PATCH | `/api/v1/expenses/<id>/` |
| Delete an expense | DELETE | `/api/v1/expenses/<id>/` |

When listing expenses, you can pass these parameters:

| Parameter | What it does |
|---|---|
| `year` | The year to show (required) |
| `month` | Month number 1–12 for a single month. Leave out for the whole year. |
| `q` | A search filter using the [query language](dashboard/query-language.md). |

### Scheduled expenses

| Action | Method | Path |
|---|---|---|
| List all templates | GET | `/api/v1/scheduled/` |
| Create a template | POST | `/api/v1/scheduled/` |
| Get one template | GET | `/api/v1/scheduled/<id>/` |
| Update a template | PATCH | `/api/v1/scheduled/<id>/` |
| Delete a template | DELETE | `/api/v1/scheduled/<id>/` |

### Categories

| Action | Method | Path |
|---|---|---|
| List all categories | GET | `/api/v1/categories/` |
| Create a category | POST | `/api/v1/categories/` |
| Get one category | GET | `/api/v1/categories/<id>/` |
| Rename a category | PATCH | `/api/v1/categories/<id>/` |
| Delete a category | DELETE | `/api/v1/categories/<id>/` |

### Tags

| Action | Method | Path |
|---|---|---|
| List all tags | GET | `/api/v1/tags/` |
| Create a tag | POST | `/api/v1/tags/` |
| Get one tag | GET | `/api/v1/tags/<id>/` |
| Rename a tag | PATCH | `/api/v1/tags/<id>/` |
| Delete a tag | DELETE | `/api/v1/tags/<id>/` |

### Account info

| Action | Method | Path |
|---|---|---|
| Get your account details | GET | `/api/v1/account/` |

## A quick example

This command (for the terminal) creates a new expense:

```bash
curl -X POST https://your-comaney-address/api/v1/expenses/ \
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
{"error": "Not found"}
```

Common response codes: `200` (success), `201` (created), `400` (bad request), `401` (wrong or missing API key), `404` (not found).

See more examples in the [Postman collection](https://github.com/Leonetienne/Comaney/blob/master/api/Comaney_API.postman_collection.json).