# Demo Users

Sources: AGENTS.md (Demo users), `budget/decorators.py`, `feusers/views/demo_banner.py`,
`feusers/management/commands/reset_demo_user.py`, docs `admin-manual/environment-variables.md`.

Demo restrictions of individual features are listed in their own files with the tag
`Demo`. This file holds the overarching rules.

### No contact with real users
`req~demo.isolation~1`

The system shall never let a demo user send email, invitations, partnership requests, merge requests or other out-of-band contact to a real account, and never let a real user add a demo account as buddy, project member, partner or merge target.

Covers:
- `feat~demo~1`

Tags: Demo, Security

### No sabotage
`req~demo.no-sabotage~1`

The system shall never let a demo user change their name, email address or password, delete the account, set up second factors, generate an API key or change own AI settings.

Covers:
- `feat~demo~1`

Tags: Demo, Security

### Allowed actions
`req~demo.allowed~1`

The system shall let a demo user change currency, financial month settings and the unspent allowance action, create and manage expenses, dashboards and offline buddies, and use AI features within their individual AI budget.

Covers:
- `feat~demo~1`

Tags: Demo

### Double enforcement
`req~demo.enforcement~1`

Every demo restriction shall be enforced on the server and reflected in the UI by hiding or disabling the control.

Covers:
- `feat~demo~1`

Tags: Demo

### Demo banner
`req~demo.banner~1`

While a demo user has not accepted the demo banner in the current session, the system shall redirect every protected page to the banner, regardless of `ENABLE_DEMO_USERS`.

Covers:
- `feat~demo~1`

Tags: Demo

### Demo login gate
`req~demo.login-gate~1`

While `ENABLE_DEMO_USERS` is not `TRUE`, the system shall reject demo account logins with the generic invalid-credentials message and end existing demo sessions.

Covers:
- `feat~demo~1`

Tags: Demo

### Landing page advert
`req~demo.advert~1`

Where demo users are enabled, the landing page shall advertise the live demo with its email address.

Covers:
- `feat~demo~1`

### Demo reset
`req~demo.reset~1`

Where demo users are enabled with `DEMO_USER_EMAIL` and `DEMO_USER_PASSWORD`, when the cron runs and no demo user exists or some demo user was last seen at least one week ago, the system shall delete all demo users and create a fresh confirmed demo account "Dean Demo" with that email, password and user defaults, whose individual AI budget is `DEMO_USER_AI_BUDGET`, or the global limit when that is 0 or unset.

Covers:
- `feat~demo~1`

Tags: Demo, Operations
