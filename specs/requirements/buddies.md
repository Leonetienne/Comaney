# Buddies

Sources: former `merge-spec.md`, `buddies/services/lifecycle.py`, `buddies/services/archive.py`,
`buddies/services/trust.py`, `buddies/views/buddies.py`, `buddies/views/main.py`,
docs `user-manual/buddies/`.

## Offline buddies

### Add offline buddy
`req~buddies.offline.add~1`

When a feuser adds an offline buddy with a name of up to 128 characters, the system shall create it, visible and usable only by that feuser.

Covers:
- `feat~buddies~1`

### Rename offline buddy
`req~buddies.offline.rename~1`

The system shall let a feuser rename their offline buddies, except the Achim Archive.

Covers:
- `feat~buddies~1`

### Offline buddy picture
`req~buddies.offline.picture~1`

The system shall let a feuser upload a picture of up to 5 MB for an offline buddy or (as project admin) offline member, stored as JPEG, with initials as fallback.

Covers:
- `feat~buddies~1`

### Remove offline buddy
`req~buddies.offline.remove~1`

When a feuser removes an offline buddy, the system shall move its shared history into the feuser's Achim Archive (creating it on first use, with a one-time introduction notice), sum shares where the archive already participates, and clear recurring assignments referencing the removed buddy.

Covers:
- `feat~buddies~1`

## Achim Archive

### Archive as participant
`req~buddies.archive.participant~1`

The Achim Archive shall behave like an offline buddy (or offline member) for balances and breakdowns and be labelled "Archive".

Covers:
- `feat~buddies~1`

### Archive wipe
`req~buddies.archive.wipe~1`

When a feuser (or the project admin, for a project archive) requests to delete archived expenses, the system shall first show how many expenses paid by removed members will be deleted, how many own expenses lose a split record, and the balance change, and delete them only after confirmation.

Covers:
- `feat~buddies~1`

### Archive removal
`req~buddies.archive.remove~1`

If the Achim Archive still holds expenses, then the system shall refuse to remove it with "Achim Archive still holds expenses. Delete all archived expenses first."

Covers:
- `feat~buddies~1`

## Connecting real users

### Buddy invitation
`req~buddies.invite.send~1`

When a feuser invites an email address as buddy, the system shall send an invitation valid for 7 days that the invitee can accept or decline from the email link or the My Buddies page.

Covers:
- `feat~buddies~1`

### Invitation of unregistered addresses
`req~buddies.invite.unregistered~1`

When the invited address has no account and registration is enabled, the system shall send a sign-up invitation and link the new account automatically once it is confirmed; if registration is disabled, then the system shall refuse the invitation with a message saying so.

Covers:
- `feat~buddies~1`

### Invitation without email
`req~buddies.invite.no-email~1`

While emailing is disabled, the system shall show the registration link to share manually instead of sending an invitation email.

Covers:
- `feat~buddies~1`

### Invitation guards
`req~buddies.invite.guards~1`

If the invitee is the inviter, already a buddy, already has a pending invitation from the inviter, or is a demo account, then the system shall refuse the invitation with a specific message.

Covers:
- `feat~buddies~1`

### Revoke invitation
`req~buddies.invite.revoke~1`

The system shall let the inviter revoke pending buddy invitations and sign-up invitations.

Covers:
- `feat~buddies~1`

### Invite from project
`req~buddies.invite.from-project~1`

Any project member shall be able to invite another real member as direct buddy from the member's menu, offered only while they are not buddies and no invitation is pending.

Covers:
- `feat~buddies~1`

### Wrong account on invite link
`req~buddies.invite.wrong-account~1`

If an invitation link is opened by a logged-in feuser whose email address differs from the invitee address, then the system shall show a wrong-account page instead of accepting.

Covers:
- `feat~buddies~1`

Tags: Security

## Removing a real buddy

### Debt warning
`req~buddies.kick.debt-warning~1`

When a feuser removes a real buddy while their net balance exceeds 0.05 in either direction, the system shall require explicit confirmation of the outstanding balance.

Covers:
- `feat~buddies~1`

### History preservation on removal
`req~buddies.kick.history~1`

When a real buddy link is removed, the system shall replace each side by a new offline buddy in the other's shared non-project expenses, copy the remover's shared expenses into the removed buddy's account, clear recurring assignments that reference the other side, notify the removed buddy, and delete the link with its auto-accept settings.

Covers:
- `feat~buddies~1`

## Auto-accept trust

### Trust toggle
`req~buddies.trust.toggle~1`

The system shall let a feuser B switch on, per direct real buddy A, "Automatically accept expenses, settlements and project invitations from A", confirmed in a dialog when enabling.

Covers:
- `feat~buddies~1`

### Trust direction
`req~buddies.trust.direction~1`

The trust shall apply only in the direction it was given and exist only while A and B are direct buddies, including inside projects they share.

Covers:
- `feat~buddies~1`

### Recorded by
`req~buddies.trust.initiator~1`

The system shall record, on every action that makes an expense need another feuser's confirmation (create, edit, clone, AI Express, recurring generation and update, settlements, settlement edits), the acting feuser as the expense's initiator.

Covers:
- `feat~buddies~1`

### Automatic acceptance
`req~buddies.trust.accept~1`

When A records an expense or settlement needing confirmation by a feuser B who trusts A, the system shall immediately approve "Did you pay for this?", confirm settlement receipt as creditor (booking the "Settlement received" income), and set B's neutral participant approval to approved, never overriding a rejection, and send B an info-only email instead of a request.

Covers:
- `feat~buddies~1`

### Automatic project join
`req~buddies.trust.project-invite~1`

When project admin A invites a feuser B who trusts A, the system shall add B to the project immediately and send B an info-only email instead of an invitation.

Covers:
- `feat~buddies~1`

### Backlog on enabling
`req~buddies.trust.backlog~1`

When B enables trust in A, the system shall silently accept every pending entry initiated by A and join every open, unexpired project invitation from A.

Covers:
- `feat~buddies~1`

### Trust exclusions
`req~buddies.trust.exclusions~1`

The system shall never auto-accept merge requests or partnership invitations, never touch expenses in archived projects or join archived projects, and never treat expenses without a recorded initiator as trusted.

Covers:
- `feat~buddies~1`

### Trust visibility
`req~buddies.trust.visibility~1`

A shall see "Accepts your entries automatically" next to B in their buddy list, and the expense form and AI Express shall replace the "requires their approval" warning by "B accepts your entries automatically, so no approval is needed" when B is selected as upfront payer.

Covers:
- `feat~buddies~1`

Tags: UI

### Switching trust off
`req~buddies.trust.off~1`

When B switches trust off, the system shall keep entries already accepted.

Covers:
- `feat~buddies~1`

## Merging offline buddies and members

### Merge targets
`req~buddies.merge.targets~1`

The system shall offer "Merge into..." for every non-archive offline buddy (to its owner) and offline project member (to the project admin), with targets: another offline buddy or member in the same scope, an already linked real user in the same scope (direct buddy, or project member), or "Yourself".

Covers:
- `feat~buddies~1`

### No cross-scope merge
`req~buddies.merge.scope~1`

The system shall never merge across personal and project scope and never use the Achim Archive as source or target.

Covers:
- `feat~buddies~1`

### Immediate merge into offline member
`req~buddies.merge.dummy~1`

When the target is another offline buddy or member, the system shall, after confirmation, move all shares and upfront payments to the target, summing shares where both participate in the same expense or template, annotate affected expense notes with the original participant, and delete the source.

Covers:
- `feat~buddies~1`

### Merge into yourself
`req~buddies.merge.self~1`

When the target is "Yourself", the system shall merge immediately: in personal scope, drop the source's shares (the feuser's own share absorbs them) and take over its upfront payments; in project scope, transfer its shares and upfront payments to the admin; then delete the source.

Covers:
- `feat~buddies~1`

### Merge request to real user
`req~buddies.merge.request~1`

When the target is a real user, the system shall send a merge request (email and in-app notification) valid for 7 days that the target can accept or decline and the sender can revoke.

Covers:
- `feat~buddies~1`

### Merge acceptance
`req~buddies.merge.accept~1`

When the target accepts a merge request, the system shall transfer the offline entry's upfront payments (making the target the owner) and shares to the target, migrate personal recurring assignments, delete the offline entry and the request, and land the target on the project page for project-scope merges.

Covers:
- `feat~buddies~1`

### No new buddy link from project merge
`req~buddies.merge.no-link~1`

A project-scope merge shall never create a direct buddy link.

Covers:
- `feat~buddies~1`

### Merge integrity
`req~buddies.merge.integrity~1`

After any merge, every affected expense shall still exist, no share or template shall reference the deleted offline entry, no participant shall hold two rows on the same expense, and no expense owner shall hold an explicit share on their own expense.

Covers:
- `feat~buddies~1`

### One pending merge per source
`req~buddies.merge.single-pending~1`

If a merge request for an offline entry is pending, then the system shall refuse another merge of that entry, immediate or requested, with "already pending".

Covers:
- `feat~buddies~1`

### Merge in archived project
`req~buddies.merge.archived~1`

If the project is archived, then the system shall refuse any merge of its offline members.

Covers:
- `feat~buddies~1`

### Merge wording
`req~buddies.merge.wording~1`

All merge request texts (pages, emails, cards) shall call it a "merge request", never an invitation, state that the recipient is already a buddy or member, and attribute transferred history as tracked under the sender's offline entry.

Covers:
- `feat~buddies~1`

Tags: UI

### Merge demo rules
`req~buddies.merge.demo~1`

Demo users may merge offline entries into offline entries or themselves but shall not send merge requests, and demo accounts shall never be merge targets.

Covers:
- `feat~buddies~1`

Tags: Demo

## Pages

### My Buddies page
`req~buddies.page.my-buddies~1`

The My Buddies page shall list direct buddies with balances, pending incoming and outgoing invitations, merge requests, project invitations and the add/invite forms.

Covers:
- `feat~buddies~1`

### Buddy Expenses page
`req~buddies.page.summary~1`

The Buddy Expenses page shall show balances across all shared expenses, pending approvals and settlement receipts, the "Pay someone back" form and a date-range-scoped, searchable, sortable list of direct buddy expenses.

Covers:
- `feat~buddies~1`

### Pending badges
`req~buddies.badges~1`

The sidebar entries for buddies and projects, and each project card on the projects page, shall show red counts of pending actions in their scope (approvals, settlement receipts, invitations, merge requests).

Covers:
- `feat~buddies~1`

Tags: UI

### Demo isolation
`req~buddies.demo~1`

If a demo user tries to invite a buddy, or a real user tries to invite a demo account, then the system shall refuse it.

Covers:
- `feat~buddies~1`

Tags: Demo
