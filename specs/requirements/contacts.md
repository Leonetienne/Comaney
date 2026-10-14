# Contacts

Sources: former `merge-spec.md`, `buddies/services/lifecycle.py`, `buddies/services/archive.py`,
`buddies/services/trust.py`, `buddies/views/buddies.py`, `buddies/views/main.py`,
docs `user-manual/contacts/`.

## Offline contacts

### Add offline contact
`req~contacts.offline.add~1`

When a feuser adds an offline contact with a name of up to 128 characters, the system shall create it, visible and usable only by that feuser.

Covers:
- `feat~contacts~1`

### Rename offline contact
`req~contacts.offline.rename~1`

The system shall let a feuser rename their offline contacts, except the Achim Archive.

Covers:
- `feat~contacts~1`

### Offline contact picture
`req~contacts.offline.picture~1`

The system shall let a feuser upload a picture of up to 5 MB for an offline contact or (as project admin) offline member, stored as JPEG, with initials as fallback.

Covers:
- `feat~contacts~1`

### Remove offline contact
`req~contacts.offline.remove~1`

When a feuser removes an offline contact, the system shall move its shared history into the feuser's Achim Archive (creating it on first use, with a one-time introduction notice), sum shares where the archive already participates, and clear recurring assignments referencing the removed contact.

Covers:
- `feat~contacts~1`

## Achim Archive

### Archive as participant
`req~contacts.archive.participant~1`

The Achim Archive shall behave like an offline contact (or offline member) for balances and breakdowns and be labelled "Archive".

Covers:
- `feat~contacts~1`

### Archive wipe
`req~contacts.archive.wipe~1`

When a feuser (or the project admin, for a project archive) requests to delete archived expenses, the system shall first show how many expenses paid by removed members will be deleted, how many own expenses lose a split record, and the balance change, and delete them only after confirmation.

Covers:
- `feat~contacts~1`

### Archive removal
`req~contacts.archive.remove~1`

If the Achim Archive still holds expenses, then the system shall refuse to remove it with "Achim Archive still holds expenses. Delete all archived expenses first."

Covers:
- `feat~contacts~1`

## Connecting real users

### Contact invitation
`req~contacts.invite.send~1`

When a feuser invites an email address as contact, the system shall send an invitation valid for 7 days that the invitee can accept or decline from the email link or the Contacts page.

Covers:
- `feat~contacts~1`

### Invitation of unregistered addresses
`req~contacts.invite.unregistered~1`

When the invited address has no account and registration is enabled, the system shall send a sign-up invitation and link the new account automatically once it is confirmed; if registration is disabled, then the system shall refuse the invitation with a message saying so.

Covers:
- `feat~contacts~1`

### Invitation without email
`req~contacts.invite.no-email~1`

While emailing is disabled, the system shall show the registration link to share manually instead of sending an invitation email.

Covers:
- `feat~contacts~1`

### Invitation guards
`req~contacts.invite.guards~1`

If the invitee is the inviter, already a contact, already has a pending invitation from the inviter, or is a demo account, then the system shall refuse the invitation with a specific message.

Covers:
- `feat~contacts~1`

### Revoke invitation
`req~contacts.invite.revoke~1`

The system shall let the inviter revoke pending contact invitations and sign-up invitations.

Covers:
- `feat~contacts~1`

### Invite from project
`req~contacts.invite.from-project~1`

Any project member shall be able to invite another real member as contact from the member's menu, offered only while they are not contacts and no invitation is pending.

Covers:
- `feat~contacts~1`

### Wrong account on invite link
`req~contacts.invite.wrong-account~1`

If an invitation link is opened by a logged-in feuser whose email address differs from the invitee address, then the system shall show a wrong-account page instead of accepting.

Covers:
- `feat~contacts~1`

Tags: Security

## Removing a real contact

### Debt warning
`req~contacts.kick.debt-warning~1`

When a feuser removes a real contact while their net balance exceeds 0.05 in either direction, the system shall require explicit confirmation of the outstanding balance.

Covers:
- `feat~contacts~1`

### History preservation on removal
`req~contacts.kick.history~2`

When a real contact link is removed, the system shall, for each side, create an offline contact of the other side's name, copy every approved expense the other paid with that side's share into that side's account (paid by the offline contact, holding only that side's share, classified with that side's overlay), and put the offline contact in the other's place in that side's own shared non-project expenses and contact recurring assignments, dropping the other's overlays and initiated-by marks there; then expire pending invitations, notify the removed contact and delete the link with its auto-accept settings. Afterwards the two share no expense, each side's shares and amounts stay unchanged, and other participants see no change.

Covers:
- `feat~contacts~1`

### Invitations on removal
`req~contacts.kick.invites~1`

When a real contact link is removed, the system shall delete every pending project invitation, pending partnership invitation and offline contact merge request between the two feusers, in both directions.

Covers:
- `feat~contacts~1`

## Auto-accept trust

### Trust toggle
`req~contacts.trust.toggle~1`

The system shall let a feuser B switch on, per direct real contact A, "Automatically accept expenses, settlements and project invitations from A", confirmed in a dialog when enabling.

Covers:
- `feat~contacts~1`

### Trust direction
`req~contacts.trust.direction~1`

The trust shall apply only in the direction it was given and exist only while A and B are contacts, including inside projects they share.

Covers:
- `feat~contacts~1`

### Recorded by
`req~contacts.trust.initiator~1`

The system shall record, on every action that makes an expense need another feuser's confirmation (create, edit, clone, AI Express, recurring generation and update, settlements, settlement edits), the acting feuser as the expense's initiator.

Covers:
- `feat~contacts~1`

### Automatic acceptance
`req~contacts.trust.accept~1`

When A records an expense or settlement needing confirmation by a feuser B who trusts A, the system shall immediately approve "Did you pay for this?", confirm settlement receipt as creditor (booking the "Settlement received" income), and set B's neutral participant approval to approved, never overriding a rejection, and send B an info-only email instead of a request.

Covers:
- `feat~contacts~1`

### Automatic project join
`req~contacts.trust.project-invite~1`

When project admin A invites a feuser B who trusts A, the system shall add B to the project immediately and send B an info-only email instead of an invitation.

Covers:
- `feat~contacts~1`

### Backlog on enabling
`req~contacts.trust.backlog~1`

When B enables trust in A, the system shall silently accept every pending entry initiated by A and join every open, unexpired project invitation from A.

Covers:
- `feat~contacts~1`

### Trust exclusions
`req~contacts.trust.exclusions~1`

The system shall never auto-accept merge requests or partnership invitations, never touch expenses in archived projects or join archived projects, and never treat expenses without a recorded initiator as trusted.

Covers:
- `feat~contacts~1`

### Trust visibility
`req~contacts.trust.visibility~1`

A shall see "Accepts your entries automatically" next to B in their contact list, and the expense form and AI Express shall replace the "requires their approval" warning by "B accepts your entries automatically, so no approval is needed" when B is selected as upfront payer.

Covers:
- `feat~contacts~1`

Tags: UI

### Switching trust off
`req~contacts.trust.off~1`

When B switches trust off, the system shall keep entries already accepted.

Covers:
- `feat~contacts~1`

## Merging offline contacts and members

### Merge targets
`req~contacts.merge.targets~1`

The system shall offer "Merge into..." for every non-archive offline contact (to its owner) and offline project member (to the project admin), with targets: another offline contact or member in the same scope, an already linked real user in the same scope (contact, or project member), or "Yourself".

Covers:
- `feat~contacts~1`

### No cross-scope merge
`req~contacts.merge.scope~1`

The system shall never merge across personal and project scope and never use the Achim Archive as source or target.

Covers:
- `feat~contacts~1`

### Immediate merge into offline member
`req~contacts.merge.dummy~1`

When the target is another offline contact or member, the system shall, after confirmation, move all shares and upfront payments to the target, summing shares where both participate in the same expense or template, annotate affected expense notes with the original participant, and delete the source.

Covers:
- `feat~contacts~1`

### Merge into yourself
`req~contacts.merge.self~1`

When the target is "Yourself", the system shall merge immediately: in personal scope, drop the source's shares (the feuser's own share absorbs them) and take over its upfront payments; in project scope, transfer its shares and upfront payments to the admin; then delete the source.

Covers:
- `feat~contacts~1`

### Merge request to real user
`req~contacts.merge.request~1`

When the target is a real user, the system shall send a merge request (email and in-app notification) valid for 7 days that the target can accept or decline and the sender can revoke.

Covers:
- `feat~contacts~1`

### Duplicate warning on merge into a real contact
`req~contacts.merge.overlap-warning~1`

When a feuser sends or accepts a request to merge an offline contact into a real contact, and the offline contact's contact expenses and the real contact's own contact expenses with their offline contacts include expenses of equal title and amount, the system shall show an OK/Cancel warning listing those expenses in a scrollable list with a button that copies the list as text to the clipboard.

Covers:
- `feat~contacts~1`

### Merge acceptance
`req~contacts.merge.accept~2`

When the target accepts a merge request, the system shall put the target in the offline entry's place in every reference, the same way for contacts and projects: expenses the offline entry paid become the target's own (a previous owner with a share keeps it and gets their category and tags as overlay), its shares become the target's (summed into an existing share of the target), and personal recurring assignments are migrated; expense notes stay unchanged. The system shall then delete the offline entry and the request, and land the target on the project page for project-scope merges.

Covers:
- `feat~contacts~1`

### No new contact link from project merge
`req~contacts.merge.no-link~1`

A project-scope merge shall never create a contact link.

Covers:
- `feat~contacts~1`

### Merge integrity
`req~contacts.merge.integrity~2`

After any merge, every affected expense shall still exist, no share or template shall reference the deleted offline entry, no participant shall hold two rows on the same expense, and no payer shall hold an explicit share on an expense they paid.

Covers:
- `feat~contacts~1`

### One pending merge per source
`req~contacts.merge.single-pending~1`

If a merge request for an offline entry is pending, then the system shall refuse another merge of that entry, immediate or requested, with "already pending".

Covers:
- `feat~contacts~1`

### Merge in archived project
`req~contacts.merge.archived~1`

If the project is archived, then the system shall refuse any merge of its offline members.

Covers:
- `feat~contacts~1`

### Merge wording
`req~contacts.merge.wording~1`

All merge request texts (pages, emails, cards) shall call it a "merge request", never an invitation, state that the recipient is already a contact or member, and attribute transferred history as tracked under the sender's offline entry.

Covers:
- `feat~contacts~1`

Tags: UI

### Merge demo rules
`req~contacts.merge.demo~1`

Demo users may merge offline entries into offline entries or themselves but shall not send merge requests, and demo accounts shall never be merge targets.

Covers:
- `feat~contacts~1`

Tags: Demo

## Pages

### Contacts page
`req~contacts.page.contacts~1`

The Contacts page shall list contacts with balances, pending incoming and outgoing invitations, merge requests, project invitations and the add/invite forms.

Covers:
- `feat~contacts~1`

### Contact Expenses page
`req~contacts.page.summary~1`

The Contact Expenses page shall show balances across all shared expenses, pending approvals and settlement receipts, the "Pay someone back" form and a date-range-scoped, searchable, sortable list of contact expenses.

Covers:
- `feat~contacts~1`

### Pending badges
`req~contacts.badges~1`

The sidebar entries for contacts and projects, and each project card on the projects page, shall show red counts of pending actions in their scope (approvals, settlement receipts, invitations, merge requests).

Covers:
- `feat~contacts~1`

Tags: UI

### Demo isolation
`req~contacts.demo~1`

If a demo user tries to invite a contact, or a real user tries to invite a demo account, then the system shall refuse it.

Covers:
- `feat~contacts~1`

Tags: Demo
