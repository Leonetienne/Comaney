# REST API

Sources: `api/`, `api/Comaney_API.postman_collection.json`, docs `user-manual/api-access.md`.

### Base path and format
`req~api.base~1`

The system shall serve the API under `/api/v1/` with JSON request and response bodies.

Covers:
- `feat~api~1`

### Bearer authentication
`req~api.auth~1`

The system shall authenticate API requests by `Authorization: Bearer <api key>` and answer 401 with an error message if the key is missing or unknown.

Covers:
- `feat~api~1`

Tags: Security

### Session callers and CSRF
`req~api.csrf~1`

If an API request without a Bearer header authenticates through the browser session and uses an unsafe method, then the system shall require a valid CSRF token and answer 403 otherwise.

Covers:
- `feat~api~1`

Tags: Security

### Data scope
`req~api.scope~1`

The system shall return and modify only data owned by the authenticated feuser and answer 404 for anything else.

Covers:
- `feat~api~1`

Tags: Security

### Error format
`req~api.errors~1`

The system shall answer errors as `{"error": "<message>"}` with status 400, 401, 403, 404 or 405.

Covers:
- `feat~api~1`

### Expenses resource
`req~api.expenses~1`

The system shall offer list and create on `/expenses/` and get, update (PATCH) and delete on `/expenses/<id>/`.

Covers:
- `feat~api~1`

### Expense listing scope
`req~api.expenses.list~1`

When listing expenses, the system shall use `date_from` and `date_to` (ISO dates, both required together) if given, otherwise the financial `year` and optional `month` (default current), and filter by `q` in the query language, which overrides the period when it contains a date comparison.

Covers:
- `feat~api~1`

### Expense validation
`req~api.expenses.validate~1`

The system shall require title, type and value on create, enforce the same limits as the web form (title and payee 128, note 1024 characters, type in `expense`, `income`, `savings_dep`, `savings_wit`, positive decimal value, ISO due date or null, own category and tags), and reject violations with 400 and a message naming the field.

Covers:
- `feat~api~1`

### Settlement protection
`req~api.expenses.settlements~1`

If an API client tries to edit a settlement or delete an approved settlement, then the system shall answer 403.

Covers:
- `feat~api~1`

### Recurring expenses resource
`req~api.scheduled~1`

The system shall offer list, create, get, update and delete for recurring templates on `/scheduled/`, applying the schedule confirmation flags `confirm_modify_schedule` and `confirm_modify_schedule_window` as in [scheduled.md](scheduled.md).

Covers:
- `feat~api~1`

### Categories and tags resources
`req~api.catalog~1`

The system shall offer list, create, get, rename and delete for `/categories/` and `/tags/`, with Catalog Partnership synchronisation as in the web UI.

Covers:
- `feat~api~1`

### Account resource
`req~api.account~1`

The system shall return the feuser's account details on `GET /account/`, never including secrets.

Covers:
- `feat~api~1`

Tags: Security

### Dashboard summary
`req~api.dashboard~1`

The system shall return on `GET /dashboard/` the financial month range, currency, income, paid and outstanding expenses, savings deposited and withdrawn, and the resulting balance for the requested or current financial month.

Covers:
- `feat~api~1`

### Postman collection
`req~api.postman~1`

The repository shall ship a Postman collection covering the API.

Covers:
- `feat~api~1`
