# System Features

Each feature groups the requirements in one file under [requirements/](requirements/).

### Accounts and authentication
`feat~accounts~1`

Registration, email confirmation, login, logout, password reset, email change,
account deletion and session handling.

Needs: req

### Second-factor authentication
`feat~twofa~1`

Multiple second factors per feuser (TOTP, WebAuthn, email code, YubiKey OTP), primary
factor, recovery code, login challenge, factor management.

Needs: req

### Profile and personal settings
`feat~profile~1`

Profile picture, backdrop, personal info, financial month settings, unspent allowance
action, notification preferences, AI settings, early access, API key.

Needs: req

### Expense records
`feat~expenses~1`

Creating, editing, cloning, settling, deactivating and deleting expenses, the expense
list, bulk actions, save checks and the overlay editor.

Needs: req

### Financial periods and date ranges
`feat~periods~1`

Financial month and year computation, the date range picker, Personal/Shared mode.

Needs: req

### Query language
`feat~query~1`

The search mini-language shared by expense search and dashboard card queries.

Needs: req

### Recurring expenses
`feat~scheduled~1`

Recurring expense templates and their materialisation into expense records.

Needs: req

### Categories and tags
`feat~catalog~1`

Per-feuser category and tag catalogs.

Needs: req

### Unclassified expenses
`feat~unclassified~1`

The page and badge for expenses missing a category or tags, with inline and AI fixing.

Needs: req

### Dashboards
`feat~dashboard~1`

Multiple dashboards with YAML-configured cards, presets, layout and AI card assist.

Needs: req

### Notifications
`feat~notifications~1`

Due-date reminder emails, in-app notifications and notification preferences.

Needs: req

### Buddies
`feat~buddies~1`

Direct buddies (real and offline), invitations, auto-accept trust, merging offline
buddies and the Achim Archive.

Needs: req

### Shared expenses and settlements
`feat~sharing~1`

Participants and shares, upfront payers, approvals, settlements and debt computation.

Needs: req

### Projects
`feat~projects~1`

Shared and solo projects with members, permissions, tabs, insights, archiving.

Needs: req

### Catalog Partnerships
`feat~partnership~1`

Synchronised tag and category catalogs between partners.

Needs: req

### AI
`feat~ai~1`

AI provider framework, access and budgets, and the AI features: AI Express, tag
suggestion, card assist, partnership mapping, unclassified solving.

Needs: req

### Sankey Studio
`feat~sankey~1`

Early access node editor and Sankey chart generation.

Needs: req

### REST API
`feat~api~1`

Bearer-token JSON API for expenses, recurring expenses, categories, tags, account and
dashboard summary.

Needs: req

### Data export
`feat~export~1`

CSV export of the expense list and full account export, project and buddy exports.

Needs: req

### Demo users
`feat~demo~1`

Shared public demo accounts and their restrictions.

Needs: req

### Administration and operations
`feat~operations~1`

Configuration, startup validation, cron jobs, management commands, admin pages,
public pages and the contact form.

Needs: req

### User interface framework
`feat~ui~1`

Cross-cutting UI behaviour: navigation badges, toasts, dialogs, intros, help links,
theming.

Needs: req

### Quality attributes
`feat~quality~1`

Security, privacy, self-containment, reliability and maintainability requirements.

Needs: req

### Design constraints
`feat~constraints~1`

Architectural rules maintainers must keep.

Needs: req
