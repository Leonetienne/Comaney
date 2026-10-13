# Catalog Partnerships

Sources: former `partnership-spec.md`, `buddies/services/partnership.py`,
`buddies/services/partnership_ai.py`, `buddies/views/partnership.py`,
docs `user-manual/catalog-partnerships.md`.

## Membership

### One partnership per feuser
`req~partnership.single~1`

The system shall let a feuser belong to at most one Catalog Partnership at a time; a partnership may have any number of members.

Covers:
- `feat~partnership~1`

### Connection required
`req~partnership.connection~1`

If the invitee shares neither a direct buddy link nor a project with the inviter, then the system shall refuse the invitation with "No mutual connection with this user."

Covers:
- `feat~partnership~1`

Tags: Security

### Invite eligibility
`req~partnership.invite.eligibility~1`

The "Invite as partner" option in My Buddies and in a project's member menu shall appear only for real users who are not already the feuser's partner and not in another partnership; the system shall refuse invitations to users already in a partnership.

Covers:
- `feat~partnership~1`

### Invite flow
`req~partnership.invite.send~1`

When a feuser confirms the explanatory dialog and sends a partnership invitation, the system shall create the partnership with the inviter as onboarded member if none exists, store a pending invitation, email the invitee and notify them in-app.

Covers:
- `feat~partnership~1`

### Cancel invitation
`req~partnership.invite.cancel~1`

The system shall let the inviter cancel a pending partnership invitation.

Covers:
- `feat~partnership~1`

### Invitation surface
`req~partnership.invite.surface~1`

While a feuser has a pending partnership invitation, the system shall show a badge on "Categories & Tags", an invitation card with Accept and Reject on that page, and a reminder banner (stoerer) on other pages until onboarding is completed or declined.

Covers:
- `feat~partnership~1`

Tags: UI

### Invitation addressee
`req~partnership.invite.addressee~1`

If a feuser opens a partnership invitation addressed to another email address, then the system shall refuse it.

Covers:
- `feat~partnership~1`

Tags: Security

### Decline
`req~partnership.invite.decline~1`

When the invitee rejects the invitation or chooses "I don't want a partnership", the system shall mark it declined, change nothing in the invitee's catalog, clear the stored wizard progress, and notify the inviter.

Covers:
- `feat~partnership~1`

### Demo exclusion
`req~partnership.demo~1`

If a demo user tries to use Catalog Partnerships, or a real user invites a demo account, then the system shall refuse it.

Covers:
- `feat~partnership~1`

Tags: Demo

## Onboarding wizard

### Wizard steps
`req~partnership.wizard.steps~1`

When the invitee accepts, the system shall open a four-step wizard: introduction, tag mapping, category mapping, review and apply, with Back and "Later" available.

Covers:
- `feat~partnership~1`

### Progress persistence
`req~partnership.wizard.persist~1`

The wizard shall save its decisions in the browser per invitation and restore them on reopening, reconciled against the current partnership catalog: entries added since appear as new rows, removed entries drop out.

Covers:
- `feat~partnership~1`

### Auto-matched rows
`req~partnership.wizard.auto-match~1`

The wizard shall pre-resolve, read-only, every invitee tag and category whose title exactly matches one in the partnership catalog.

Covers:
- `feat~partnership~1`

### Mapping decision required
`req~partnership.wizard.decision~1`

For each unmatched invitee tag or category the wizard shall require either a target from the partnership catalog or "Drop", and shall not proceed while any row is undecided; it shall list undecided entries and partnership entries that nothing maps to.

Covers:
- `feat~partnership~1`

### AI mapping suggestion
`req~partnership.wizard.ai~1`

Where AI is available, the wizard shall offer "Let AI decide", which pre-fills unmatched rows with suggested targets from the partnership catalog or Drop, all still editable; on failure it shall show "AI suggestion failed. Please map manually."

Covers:
- `feat~partnership~1`

### Review summary
`req~partnership.wizard.review~1`

The review step shall show how many tags and categories will be remapped and dropped.

Covers:
- `feat~partnership~1`

### Apply
`req~partnership.wizard.apply~2`

When the invitee applies, the system shall replace the invitee's catalog with the partnership catalog and remap the tags and category of every record carrying the invitee's labels (own expenses, own recurring expenses and own expense overlays) to the mapped targets, removing dropped and unmapped labels and deleting overlays left without category, tags and note; it shall then mark onboarding complete and notify the inviter and the other partners.

Covers:
- `feat~partnership~1`

### Apply integrity
`req~partnership.wizard.apply-guard~1`

If the apply request is not from the invitee of a pending invitation or contains an invalid mapping, then the system shall reject it without changing anything.

Covers:
- `feat~partnership~1`

Tags: Security

## Synchronisation

### Sync on change
`req~partnership.sync~1`

When a partner with completed onboarding creates, renames or deletes a tag or category, the system shall apply the same change, matched by title, to every other partner with completed onboarding; deleting removes the label from their expenses too.

Covers:
- `feat~partnership~1`

### No sync during onboarding
`req~partnership.sync.onboarding~1`

While a member has not completed onboarding, the system shall not sync changes to them; on completion they receive the then-current catalog.

Covers:
- `feat~partnership~1`

### Conflict resolution
`req~partnership.sync.conflicts~1`

The system shall resolve concurrent catalog changes as last write wins.

Covers:
- `feat~partnership~1`

## Leaving

### Partner list
`req~partnership.partners~1`

The Categories & Tags page shall list the other partners with picture, name, join date and status (Pending, Onboarding, Active), each with "Kick", and a "Leave partnership" button.

Covers:
- `feat~partnership~1`

### Leave
`req~partnership.leave~1`

When a partner leaves after confirmation, the system shall remove their membership, keep their current catalog, and notify the remaining partners.

Covers:
- `feat~partnership~1`

### Kick
`req~partnership.kick~1`

When any partner kicks another after confirmation, the system shall remove that member, who keeps their catalog, and notify the kicked member and the remaining partners.

Covers:
- `feat~partnership~1`

### Auto-removal
`req~partnership.auto-remove~1`

When a buddy link or project membership is removed and a partner no longer shares any buddy link or project with any other partner, the system shall remove that partner from the partnership and notify the remaining partners.

Covers:
- `feat~partnership~1`

### Dissolution
`req~partnership.dissolve~1`

When a partnership drops to one member or none, the system shall dissolve it.

Covers:
- `feat~partnership~1`

### Notification classes
`req~partnership.notification-classes~1`

The system shall send partnership events affecting the recipient (invite received, invite accepted or declined, being removed) under "partnership changes (you)" and events about others (joined, left, kicked, auto-removed) under "partnership changes (others)".

Covers:
- `feat~partnership~1`
