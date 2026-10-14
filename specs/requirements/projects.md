# Projects

Sources: `buddies/views/projects.py`, `buddies/services/group.py`, `buddies/models/project.py`,
`build/js/project_member_add.js`, docs `user-manual/projects.md`, AGENTS.md.

## Lifecycle

### Create project
`req~projects.create~1`

When a feuser creates a project with a name of up to 128 characters and optional description and picture, the system shall create it with the feuser as admin and only member, and open it.

Covers:
- `feat~projects~1`

### Project list
`req~projects.list~1`

The projects page shall list the feuser's projects in their own drag-and-drop order, with archived projects marked "Archived" and always at the bottom.

Covers:
- `feat~projects~1`

### Project picture
`req~projects.picture~1`

The system shall store an uploaded project picture scaled to fit 1200x600 as WebP.

Covers:
- `feat~projects~1`

### Solo project
`req~projects.solo~1`

While a project has no member other than the admin, the system shall hide debt graphs, the spending pie chart, settlement tools and split controls; adding any member, real or offline, shall show them.

Covers:
- `feat~projects~1`

### Last modified
`req~projects.lastmod~1`

The system shall update a project's last-modified time on every mutation of the project or its expenses.

Covers:
- `feat~projects~1`

## Tabs

### Three tabs
`req~projects.tabs~1`

A project page shall have the tabs Expense list (default), Insights and Settings, sharing one header with name, picture and tab navigation.

Covers:
- `feat~projects~1`

Tags: UI

### Expense list tab
`req~projects.tab.expenses~1`

The Expense list tab shall show the project's total spending, pending approvals and settlements, the settle-up tools, and the searchable, sortable list of all project expenses over the entire history with each person's share.

Covers:
- `feat~projects~1`

### Insights tab
`req~projects.tab.insights~1`

The Insights tab shall show the feuser's balance summary, raw and simplified debt graphs, the spending breakdown pie chart per member, spending over time, and spending by tag, laid out in a grid of two to three columns collapsing to one below 560 px.

Covers:
- `feat~projects~1`

### Tag chart visibility
`req~projects.tab.tag-chart~1`

The spending-by-tag chart shall use the feuser's own tags or their overlay tags, never other members' tags, at full expense value by default and at the feuser's own share when "Show only my share" is on.

Covers:
- `feat~projects~1`

Tags: Privacy

### Settings tab
`req~projects.tab.settings~1`

The Settings tab shall show the member list, the cosmetics form for those allowed, and the admin actions.

Covers:
- `feat~projects~1`

### Project FAB
`req~projects.fab~1`

All three tabs shall offer the add button with "Manual" and, where AI is available, "AI" which opens AI Express prefilled with "Create all expenses for project '<name>' ".

Covers:
- `feat~projects~1`

## Permissions

### Admin-only actions
`req~projects.admin-only~1`

The system shall allow only the admin to invite and remove members, add and manage offline members, transfer admin rights, trigger project-wide settlement, set the permission laxity, and archive, unarchive or delete the project.

Covers:
- `feat~projects~1`

Tags: Security

### Cosmetics permission
`req~projects.cosmetics~1`

The system shall let the admin always, and other members only when laxity is "Any member", edit name, description, picture and AI preprompt; the default laxity shall be "Admin only".

Covers:
- `feat~projects~1`

### Laxity setting
`req~projects.laxity~1`

When the admin picks "Who can edit cosmetics" on the Settings tab, the system shall save it immediately.

Covers:
- `feat~projects~1`

### AI preprompt
`req~projects.ai-preprompt~1`

The system shall store a project AI preprompt of up to 500 characters, edited below the description and shown only where AI is available, and keep the stored value when a rename request omits it.

Covers:
- `feat~projects~1`

## Members

### Invite by email
`req~projects.invite~1`

When the admin invites an email address, the system shall send a project invitation valid for 7 days, or a sign-up and join link for unregistered addresses, list pending invitations on the Settings tab and let the admin revoke them.

Covers:
- `feat~projects~1`

### Invitation guards
`req~projects.invite.guards~1`

If the invitee is the admin, already a member, a demo account, or the project is archived, then the system shall refuse the invitation.

Covers:
- `feat~projects~1`

### Contact suggestions
`req~projects.invite.suggestions~1`

The invite field shall suggest the admin's contacts who are not members, matching typed text against first name, last name or email, and show whether the typed address belongs to a contact.

Covers:
- `feat~projects~1`

Tags: UI

### Offline member warnings
`req~projects.offline.warning~1`

When the admin types an offline member name that looks like an email address or matches a contact, the form shall show one warning (email first) and ask for confirmation on submit, without shifting the layout.

Covers:
- `feat~projects~1`

Tags: UI

### Accept invitation
`req~projects.invite.accept~1`

When an invitee accepts a project invitation, the system shall add them as member, notify the admin and show the project.

Covers:
- `feat~projects~1`

### Remove real member
`req~projects.remove-member~1`

When the admin removes a real member, the system shall revoke their access and replace them with an offline member of the same name in all project expenses.

Covers:
- `feat~projects~1`

### Remove offline member
`req~projects.remove-offline~1`

When the admin removes an offline member, the system shall move its history to the project's Achim Archive.

Covers:
- `feat~projects~1`

### Leave project
`req~projects.leave~1`

When a non-admin member leaves, the system shall replace them with an offline member of the same name; if the admin tries to leave while other real members exist, then the system shall require transferring admin rights first, and if the admin is the only real member, then the system shall point them to deleting instead.

Covers:
- `feat~projects~1`

### Removed member as payer
`req~projects.removed-payer~2`

When a real member is removed or leaves, the system shall make their offline member the upfront payer of every project expense they paid, transfer ownership of every project expense they owned to the admin with the admin's own category and tags and a 0% share for the admin where they had none, remove every other project reference to them, and keep all expenses, shares, amounts, approval states and debts between members unchanged.

Covers:
- `feat~projects~1`

### Transfer admin
`req~projects.transfer~1`

When the admin transfers admin rights to another real member, the system shall make that member admin immediately; the former admin stays a member.

Covers:
- `feat~projects~1`

## Archive and delete

### Archive effects
`req~projects.archive~1`

While a project is archived, the system shall refuse new expenses, edits, deletions, unlinks, new settlements, invitations, offline member changes and merges, but allow confirming or rejecting in-flight settlements, leaving and admin transfer.

Covers:
- `feat~projects~1`

### Archived in forms and queries
`req~projects.archive.forms~1`

The system shall hide archived projects from assignment dropdowns while `project=<name>` queries still match their expenses.

Covers:
- `feat~projects~1`

### Delete project
`req~projects.delete~1`

When the admin, as the only real member, confirms deletion by typing the project name, the system shall delete the project with all its expenses and files; a wrong name shall cancel the deletion.

Covers:
- `feat~projects~1`

## Project expenses

### Delete project expense
`req~projects.expense.delete~1`

The system shall let only the expense owner delete a project expense, removing it for everyone.

Covers:
- `feat~projects~1`

### Unlink project expense
`req~projects.expense.unlink~1`

When the expense owner or the project admin unlinks an expense from a project, the system shall remove the project assignment and its shares and keep it as a personal expense of the owner; an expense awaiting approval must be approved first.

Covers:
- `feat~projects~1`
