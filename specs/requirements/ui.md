# User Interface Framework

Sources: `templates/base.html`, `templates/budget_base.html`, `templates/partials/`,
`budget/templatetags/action_badges.py`, `feusers/context_processors.py`,
`feusers/help_fab.py`, `feusers/intros.py`, `build/scss/`, AGENTS.md.

### Navigation
`req~ui.nav~1`

The logged-in layout shall provide a sidebar with Dashboard, Expenses, Add Expense, Recurring Expenses, Categories & Tags, Unclassified Expenses, Sankey Studio (with early access only), Contacts, Contact Expenses, Projects and Settings, plus a header with notifications bell and profile menu.

Covers:
- `feat~ui~1`

### Action badges
`req~ui.badges~1`

Sidebar entries shall show a red count of pending actions in their area through one shared badge mechanism, hidden at zero.

Covers:
- `feat~ui~1`

### Toasts
`req~ui.toasts~1`

The system shall show every transient flash message, server-side or client-side, as a toast stacked in the bottom-right corner without reflowing page content, closing after 5 seconds or by its close button.

Covers:
- `feat~ui~1`

### Confirm dialogs
`req~ui.confirm~1`

The system shall ask for irreversible or consequential actions through one in-page confirm dialog with OK, Cancel and an optional third button, never the browser's native dialog.

Covers:
- `feat~ui~1`

### Save checks
`req~ui.save-checks~1`

Before a form with registered save checks submits, the system shall run blocking checks first, then show warning dialogs one after another, and submit once after the last one is accepted.

Covers:
- `feat~ui~1`

### Add button menu
`req~ui.fab~2`

The add button on the expense list and project pages shall open a small menu with "Manual" and, where AI is available, "AI".
While the menu is closed, it shall let clicks through to the page content beneath it.

Covers:
- `feat~ui~1`

### Help button
`req~ui.help~1`

Pages with a matching user manual chapter shall show a help button linking to it.

Covers:
- `feat~ui~1`

### Welcome intro
`req~ui.intro~1`

When a feuser opens the app for the first time, the system shall show a welcome introduction once and remember that it was seen.

Covers:
- `feat~ui~1`

### Upgrade intro
`req~ui.upgrade-intro~1`

The system shall show the "what's new" introduction once per intro version to feusers created on an older app version, but not within 30 days of their welcome intro.

Covers:
- `feat~ui~1`

### Modal focus
`req~ui.modal-focus~1`

When an intro modal closes, the system shall return focus to the previously focused element.

Covers:
- `feat~ui~1`

### Theming
`req~ui.theme~1`

The UI shall follow the browser's light or dark preference throughout, including charts and dashboard card colours.

Covers:
- `feat~ui~1`

### Responsive layout
`req~ui.responsive~1`

Every page shall be usable on phone-width screens; dashboards switch to a 6-column layout and dashboard tabs to a selector.

Covers:
- `feat~ui~1`

### Labels and messages
`req~ui.wording~1`

UI labels shall be short, buttons verbs, and status and error messages shall state what happened in few words without apologies.

Covers:
- `feat~ui~1`

### Offline member naming
`req~ui.offline-label~1`

The UI shall call a dummy "offline member" in project context and "offline contact" in personal context, and call projects "project", never "group".

Covers:
- `feat~ui~1`
