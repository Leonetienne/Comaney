# Notifications

Sources: `budget/notifications.py`, `feusers/notifications_service.py`,
`feusers/models/notification.py`, `feusers/views/notifications.py`,
docs `user-manual/notifications.md`, `user-manual/account-settings.md`.

## Notification classes and delivery

### Notification types
`req~notifications.types~1`

The system shall classify every notification into one of: expense due reminders, expense marked as paid, shared expense participation, expense assignment (upfront payer), participant decisions, settlements, project membership, partnership changes affecting the feuser, and partnership changes affecting others.

Covers:
- `feat~notifications~1`

### Per-type preference
`req~notifications.preference~1`

If a feuser has turned off a notification type, then the system shall create neither an in-app notification nor an email of that type for them.

Covers:
- `feat~notifications~1`

### Email master switch
`req~notifications.email-master~1`

While a feuser's email notifications are off, the system shall still create in-app notifications of enabled types but send no notification email.

Covers:
- `feat~notifications~1`

### Invitations always sent
`req~notifications.invites~1`

The system shall send invitation emails (contact, project, partnership, merge request) regardless of notification preferences.

Covers:
- `feat~notifications~1`

### No email to demo users
`req~notifications.demo~1`

The system shall never send notification emails to demo users.

Covers:
- `feat~notifications~1`

Tags: Demo

### Emailing disabled
`req~notifications.no-email~1`

While emailing is disabled, the system shall send no emails at all and continue to create in-app notifications.

Covers:
- `feat~notifications~1`

## In-app notifications

### Bell
`req~notifications.bell~1`

The header shall show a bell with the count of unread notifications.

Covers:
- `feat~notifications~1`

Tags: UI

### Notification list
`req~notifications.list~1`

When the feuser opens the bell, the system shall list up to 60 notifications, unread first then newest first, each linking to its related expense, project or person where applicable.

Covers:
- `feat~notifications~1`

### Mark read and clean up
`req~notifications.read~1`

The system shall let a feuser mark notifications as read and delete all read notifications.

Covers:
- `feat~notifications~1`

## Due-date reminders

### Reminder preconditions
`req~notifications.reminder.preconditions~1`

The system shall send due-date reminders only for active, unsettled expenses that have a due date and notify enabled, owned by feusers with reminders enabled.

Covers:
- `feat~notifications~1`

### Reminder sequence
`req~notifications.reminder.sequence~1`

During each cron run, the system shall send at most one reminder per expense and class in the order "due soon" (2 to 4 days before), "due tomorrow", "due today" and "overdue" (past due), never sending a class lower than one already sent.

Covers:
- `feat~notifications~1`

### No stale reminders on save
`req~notifications.reminder.initial-class~1`

When an expense is created or edited, the system shall set its last-sent class to the class matching its current due date, so that saving an expense never triggers reminders for steps already passed.

Covers:
- `feat~notifications~1`

### Settled notification
`req~notifications.settled~1`

When an expense becomes settled (manually, automatically or via email link), the system shall send one "settled" notification for it if not already sent.

Covers:
- `feat~notifications~1`

### Reminder email links
`req~notifications.reminder.links~1`

Every reminder email shall contain links to mark the expense as settled, mute this expense and mute all notifications, each acting on the logged-in owner's account.

Covers:
- `feat~notifications~1`

### Mute all
`req~notifications.mute-all~1`

When the feuser follows "mute all notifications", the system shall turn their email notifications off.

Covers:
- `feat~notifications~1`
