# REST API

Sources: `api/registry.py`, `api/operations/`, `api/rest.py`, `api/permissions.py`, `api/Comaney_API.postman_collection.json`,
docs `user-manual/api-access.md`.

## General

### Base path and format
`req~api.base~2`

The system shall serve the API under `/api/v2/` with JSON request and response bodies and serve no other API version.

Covers:
- `feat~api~1`

### Bearer authentication
`req~api.auth~1`

The system shall authenticate API requests by `Authorization: Bearer <api key>` and answer 401 with an error message if the key is missing or unknown.

Covers:
- `feat~api~1`

Tags: Security

### API key permissions
`req~api.key-permissions~1`

The system shall limit requests authenticated by the API key to the key's permissions, using the concerns and the write-includes-read rule of agent keys (see [mcp.md](mcp.md)), and answer a request the key does not allow with 403 naming the missing concern and permission, performing no part of it.

Covers:
- `feat~api~1`

Tags: Security

### API key default permissions
`req~api.key-permissions.default~1`

The system shall give the API key read and write on every concern by default and keep its permissions when the key is revoked and a new one generated.

Covers:
- `feat~api~1`

### API key restrict panel
`req~api.key-permissions.panel~1`

When a feuser clicks "Restrict" on the API key, the system shall show the agent key Restrict panel for it.

Covers:
- `feat~api~1`

Tags: UI

### Session callers and CSRF
`req~api.csrf~2`

If an API request without a Bearer header authenticates through the browser session and uses an unsafe method, then the system shall require a valid CSRF token and answer 403 otherwise. Session callers are not limited by the API key's permissions.

Covers:
- `feat~api~1`

Tags: Security

### Data scope
`req~api.scope~2`

The system shall return only data the authenticated feuser can see in the web app, allow only changes the web app allows them, and answer 404 for records outside that scope.

Covers:
- `feat~api~1`

Tags: Security

### Error format
`req~api.errors~2`

The system shall answer errors as `{"error": "<message>"}` with status 400, 401, 403, 404, 405 or 409, answer a deletion that has nothing to report with 204 and no body, and name the offending argument in validation messages.

Covers:
- `feat~api~1`

### One definition per operation
`req~api.registry~1`

The system shall define every API operation once, with its permission concern, read or write access, method, path, parameters and description, and derive both the REST routes and the MCP tools from that definition.

Covers:
- `feat~api~1`

### Same rules as the web app
`req~api.services~1`

The system shall perform every API write through the same service functions as the equivalent web action, applying the same validation, side effects and notification emails, including participant approval resets, auto-accept trust, Catalog Partnership catalog sync and project last-modified updates.

Covers:
- `feat~api~1`

### Argument checking
`req~api.arguments~1`

The system shall check argument types and allowed values, reject unknown arguments in request bodies with 400, and ignore unknown query parameters.

Covers:
- `feat~api~1`

### Confirmation tokens
`req~api.confirm-token~1`

When a two-step operation previews its effect, the system shall return a signed token bound to the feuser, the agent key if any, the operation and the previewed state, valid for 10 minutes; if a token is invalid, expired, issued to another caller or the state changed, then the system shall change nothing and say why.

Covers:
- `feat~api~1`

Tags: Security

### Postman collection
`req~api.postman~2`

The repository shall ship a Postman collection with one request per API operation.

Covers:
- `feat~api~1`

## Expenses

### Expenses resource
`req~api.expenses~2`

The system shall offer list, create, totals and bulk actions on `/expenses/`, get, update (PATCH) and delete on `/expenses/<id>/`, clone on `/expenses/<id>/clone/` and the feuser's overlay on `/expenses/<id>/overlay/`.

Covers:
- `feat~api~1`

### Expense listing scope
`req~api.expenses.list~2`

When listing or summing expenses, the system shall use `date_from` and `date_to` if both are given, otherwise the financial `year` and `month` (default current) or the whole financial year with `view=year`, filter by `q` in the query language, and in `sharing=shared` mode include foreign expenses with every row valued at the feuser's own share.

Covers:
- `feat~api~1`

### Expense validation
`req~api.expenses.validate~2`

The system shall validate expense fields with the web form's rules, require title, type and value on create (default settled and due today), and reject violations with 400 naming the field.

Covers:
- `feat~api~1`

### Sharing through an assignment
`req~api.expenses.assignment~1`

The system shall share an expense with a contact or within a project through an `assignment` argument (mode, project, upfront payer, participants with share percent), validated like the web form's sharing section; on update a missing `assignment` keeps the sharing and `null` makes the expense personal.

Covers:
- `feat~api~1`

### Foreign expenses
`req~api.expenses.foreign~1`

When returning a foreign expense, the system shall show the feuser's own overlay category and tags, their share as effective value, and no edit or delete rights.

Covers:
- `feat~api~1`

Tags: Privacy

### Overlay
`req~api.expenses.overlay~1`

The system shall let a participant read and replace their own category, tags and note on a foreign expense they participate in, leaving the owner's classification unchanged.

Covers:
- `feat~api~1`

### Totals
`req~api.expenses.totals~1`

The system shall sum the expenses of one transaction type (default expense) in the listing scope, excluding deactivated ones, and optionally group the sum by category, tag, payee or month, resolving category and tags of foreign expenses from the feuser's overlay.

Covers:
- `feat~api~1`

### Bulk actions
`req~api.expenses.bulk~1`

The system shall apply settle, unsettle, add-tag, remove-tag, set-category and delete to a list of expense ids like the expense list's bulk actions, changing the feuser's overlay for tag and category actions on foreign expenses.

Covers:
- `feat~api~1`

### Two-step bulk delete
`req~api.expenses.bulk-delete~1`

When a bulk delete arrives without a confirmation token, the system shall delete nothing and return the own, non-settlement expenses it would delete with their count and total and a confirmation token; with a valid token it shall delete exactly those expenses.

Covers:
- `feat~api~1`

Tags: Security

### Settlement protection
`req~api.expenses.settlements~2`

If an API client tries to edit or delete a confirmed settlement, or a non-admin an approved project settlement, then the system shall answer 403.

Covers:
- `feat~api~1`

## Other resources

### Recurring expenses resource
`req~api.scheduled~2`

The system shall offer list, create, get, update, delete and clone for recurring templates on `/scheduled/`, list a template's expenses of the current financial year and apply the template to some of them, and apply the schedule confirmation flags `confirm_modify_schedule` and `confirm_modify_schedule_window` as in [scheduled.md](scheduled.md).

Covers:
- `feat~api~1`

### Categories and tags resources
`req~api.catalog~1`

The system shall offer list, create, get, rename and delete for `/categories/` and `/tags/`, with Catalog Partnership synchronisation as in the web UI.

Covers:
- `feat~api~1`

### Account resource
`req~api.account~2`

The system shall return the feuser's profile and settings on `GET /account/` and change name, currency, financial month, unspent allowance action, notification, early access and save warning settings on `PATCH /account/` with the profile page's validation, never exposing or changing email, password, second factors, keys or own AI settings.

Covers:
- `feat~api~1`

Tags: Security

### Dashboard summary
`req~api.dashboard~1`

The system shall return on `GET /dashboard/` the financial month range, currency, income, paid and outstanding expenses, savings deposited and withdrawn, and the resulting balance for the requested or current financial month.

Covers:
- `feat~api~1`

### Dashboards and cards
`req~api.dashboards~1`

The system shall offer list, create, rename and delete for dashboards, list cards with their data for a period, create, change and delete cards with the dashboard's YAML validation, and return the card YAML reference built from the user manual.

Covers:
- `feat~api~1`

### Projects
`req~api.projects~2`

The system shall offer listing projects with the feuser's balance, project details with members and simplified debts, a project overview with all members including offline ones, every expense and settlement with payer and each member's share, every member's balance, the netted expense flows and the fewest settling payments, independent of period and sharing mode, creating, editing, archiving and deleting (with the project name as confirmation), inviting by email or contact, withdrawing and answering invitations, adding, renaming and removing members, transferring admin rights, leaving, and unlinking or deleting project expenses, with the same permission checks as the project pages.

Covers:
- `feat~api~1`

### Contacts
`req~api.contacts~1`

The system shall offer listing contacts and offline contacts with balances and auto-accept flags, inviting by email or feuser, withdrawing and answering invitations, removing contacts, switching auto-accept, and adding, renaming and removing offline contacts, where removing one with an open balance needs explicit acceptance.

Covers:
- `feat~api~1`

### Pending items
`req~api.pending~1`

The system shall list everything waiting for the feuser's decision (expenses recorded with them as upfront payer, settlements to confirm as creditor, shared expenses awaiting their consent, admin decisions for offline members, and incoming contact, project and partnership invitations) and accept or reject each kind of expense decision.

Covers:
- `feat~api~1`

### Settlements
`req~api.settlements~2`

The system shall list recorded settlements (amount, date, payer, recipient, project, pending or confirmed) of a project, or those the feuser paid or received, optionally filtered by person and status, record a settlement with a contact or between two project members, and let a project admin clear all open debts of a project at once, with the same checks and notifications as the settle-up forms.

Covers:
- `feat~api~1`

### Catalog Partnership
`req~api.partnership~1`

The system shall show the feuser's partnership, invite a connected feuser, withdraw invitations, remove partners and leave, with the same checks as the Categories & Tags page.

Covers:
- `feat~api~1`

### Partnership onboarding
`req~api.partnership.onboarding~1`

The system shall return, for the open invitation to the feuser, both catalogs with the feuser's titles split into matched and unmatched; reject mappings that leave an unmatched title neither mapped to an inviter title nor explicitly dropped; preview per title how many records carry it and what it becomes, together with a confirmation token; and apply exactly the previewed mappings like the onboarding wizard.

Rationale:
The wizard drops unmapped titles silently; an API client must decide each one explicitly.

Covers:
- `feat~api~1`
