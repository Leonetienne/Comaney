# Managing Groups

This page covers everything about running a group: inviting and removing members, transferring leadership, reading the debt breakdown, and dissolving the group when you are done.

For how to create a group or invite members for the first time, see [Adding Buddies](adding-buddies.md).

## The group page

Every group has its own detail page. Get there from **My Buddies** > click **Manage** next to the group, or from **Buddy Expenses** > click the group card.

The group page shows:

- The **member list** with each person's name.
- The **expense breakdown**: all approved shared expenses with each person's share.
- **Who owes who**: two diagrams showing raw debts and a simplified minimum-payment view.
- **Your balance summary**: a plain list of who you owe and how much.
- **Pending items**: expenses waiting for approval and settlements waiting for confirmation.

## Who is the admin

Every group has one admin. The admin is the only person who can:

- Invite and remove members.
- Add offline members.
- Invite offline members to link their Comaney account.
- Transfer admin rights.
- Trigger a group-wide settlement.
- Dissolve the group.

The admin label appears next to your name on the group page when you have this role.

## Removing a member

Admin only. On the group detail page, click the **Remove** button next to the member's name.

- When you remove a real user, they lose access to the group and a read-only offline entry with their name is added so that past expenses still reference them correctly.
- When you remove an offline member (someone without a Comaney account), their shared expense history is moved to **Achim Archive** rather than deleted. See [Achim Archive](achim-archive.md) for details.

!!! note
    You cannot remove yourself as admin. Transfer admin rights first, or dissolve the group.

## Transferring admin rights

If you want to step down as admin or hand over to someone else:

1. On the group page, find the **Transfer admin** section.
2. Choose a member from the dropdown.
3. Confirm the transfer.

The chosen member becomes the new admin immediately. You keep your membership but lose admin controls.

## Leaving a group

If you are not the admin, you can leave the group at any time.

1. On the group page, click **Leave group**.
2. Confirm.

You are removed from the group and redirected to My Buddies. Your past expense history in the group stays as a read-only offline entry.

If you are the admin, you must transfer admin rights to another member before you can leave.

## Dissolving a group

Admin only. Dissolving permanently removes the group and all its connections.

1. On the group page, click **Dissolve group** and confirm.

The group disappears from all members' pages. Expenses that were part of the group are not deleted from individual members' expense lists, but they are no longer linked to the group.

!!! warning
    Dissolving a group cannot be undone. Make sure all debts are settled and everyone agrees before doing this.

## The debt diagrams

The group page shows two debt diagrams, both generated from the group's approved expenses:

**Raw debts** shows every direct debt relationship: an arrow from each person who owes money to the person they owe it to, with the amount. If two people owe each other, the smaller amount is subtracted and only the net direction is shown.

**Simplified** shows the minimum number of payments needed to settle everything. Comaney chains debts together where possible. For example, if Alex owes Bailey 10 and Bailey owes Casey 10, the simplified view shows just one arrow: Alex pays Casey 10 directly.

The **Your balance** section above the diagrams translates this into plain sentences for your own position: "You owe Alex 20" or "Bailey owes you 5".
