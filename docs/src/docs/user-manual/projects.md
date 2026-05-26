# Projects

A project is an expense container for tracking costs related to a specific goal or event. Projects work just as well for one person as they do for a group — you do not need anyone else to get started.

**Examples:**

- Repairing a motorcycle (just you)
- Beach trip 2025 with friends
- Tracking shared flat expenses with housemates

Projects are separate from your personal buddy connections. You can use them on your own, or invite other Comaney users and offline members.

## Creating a project

1. Click **Projects** in the navigation.
2. Enter a name. A description and cover image are optional.
3. Click **Create**.

You land on the new project page and become its admin.

## The project page

The project page shows everything related to that project:

- The **member list** with user.
- The **expense list**: all expenses linked to this project, with each person's share. Use the **date range bar** at the top of the page to narrow the list to a specific period. Use the search bar and sort controls above the expense list to search or sort within that range.
- **Who owes who**: two diagrams showing raw debts and a simplified minimum-payment view. Hidden for solo projects (see below).
- **Your balance**: a plain summary of who you owe and how much.
- **Pending items**: expenses waiting for approval, and settlements waiting for confirmation.

## Solo projects

A project is **solo** when you are the only member (no other real users). In solo mode, the debt diagram, settlement tools, and member split controls are hidden — they are not needed when it is just you.

Adding another person (real or offline) turns the project into a multi-member project and makes those sections visible.

## Logging expenses in a project

When creating or editing an expense, set **Expense assignment** to **Project** and choose the project from the dropdown. Only active (non-archived) projects appear in the dropdown.

For **solo projects**, the payer selection and split controls are hidden. The expense is automatically assigned entirely to you.

For **multi-member projects**, you can set who paid upfront and how the cost is divided among participants. See [Shared Expenses](buddies/shared-expenses.md) for the full guide.

## Who is the admin

Every project has one admin. The admin is the only person who can:

- Invite and remove members.
- Add offline members.
- Transfer admin rights.
- Trigger a project-wide settlement.
- Archive or delete the project.

The admin label appears next to your name on the project page.

## Inviting members

Admin only.

1. On the project page, find the **Invite a member** form.
2. Enter their email address and click **Invite**.

They receive an email with a link. Once they accept, they appear in the member list.

- If the email address is not yet registered, Comaney sends them a sign-up and project-join link.
- Pending invitations are listed on the project page and can be revoked there.

**Receiving a project invitation:** Go to **My Buddies**. The invitation appears under **Pending Invitations**. Click **View invite** to accept or decline.

## Adding an offline member

If someone in your project does not use Comaney, you can add them as an offline member.

1. On the project page, find **Add an offline member**, enter a name, and click **Add**.

You can log expenses on their behalf and settle their share yourself. You can also invite them to join Comaney later and link their account to the offline entry.

!!! note
    Adding an offline member to a solo project makes it a multi-member project. The debt diagram and settlement tools become visible.

## Merging an offline member

Admin only. You can combine an offline member's history with another entry in the project, either because two entries turn out to be the same person, or because that person now has a real Comaney account and is already a member.

1. On the project's **Manage** page, click **···** next to the offline member and choose **Merge into...**.
2. Pick a target from the list: another offline member, or a real member who has already joined the project.
3. Click **Merge** and confirm.

If you picked another offline member, the merge happens right away and cannot be undone: the shared expense history of both entries is combined, and the one you started from disappears.

If you picked a real member, they get an email and a notification asking them to approve it. The request shows up for them on this same Manage page. Once they accept, the offline member's expense history moves to their account and the offline entry disappears.

If you pick **Yourself**, the merge also happens right away, with no approval needed - useful when an offline member turns out to have been you all along. The offline entry disappears and its expense history becomes attributed to you directly.

## Connecting with a fellow member

Any member, not just the admin, can click the **···** menu next to another real member's name on the Manage tab to:

- **Invite as direct buddy** - connects you one-on-one outside the project, so you can also share personal expenses together.
- **Invite as partner** - sets up a Catalog Partnership so your tags and categories stay in sync. See [Catalog Partnerships](catalog-partnerships.md).

Each option only appears when it applies. For example, **Invite as direct buddy** disappears once you are already buddies, and **Invite as partner** disappears once they are already in a partnership.

## Removing a member

Admin only. On the project page, click **Remove** next to the member's name.

- When you remove a real user, they lose access to the project. A read-only offline entry with their name is kept so that past expenses still reference them correctly.
- When you remove an offline member, their shared expense history moves to **Achim Archive** rather than being deleted. See [Achim Archive](buddies/achim-archive.md) for details.

!!! note
    You cannot remove yourself as admin. Transfer admin rights first.

## Transferring admin rights

1. On the project page, find the **Transfer admin** section.
2. Choose a member from the dropdown.
3. Confirm.

The chosen member becomes the new admin immediately. You keep your membership but lose admin controls.

## Leaving a project

If you are not the admin, you can leave at any time from the project page. Your past expense history stays as a read-only offline entry.

If you are the admin and there are other real members, you must transfer admin rights before you can leave.

If you are the admin and the only real member, you cannot leave — you can only delete the project (see below).

## Archiving a project

Archiving freezes a project in place. Once archived:

- No new expenses can be added.
- Existing expenses cannot be edited or deleted.
- No new settlements can be created.
- In-flight settlements (sent but not yet confirmed) can still be confirmed or rejected.
- Real members can still leave, and the admin can still transfer rights.

Archived projects appear in the project list with an **Archived** badge and are sorted to the bottom. They do not appear in expense form dropdowns, but you can still filter their expenses in dashboard queries using `project=<name>`.

**To archive:** Admin only. On the project page, click **Archive project** and confirm.

**To unarchive:** Admin only. On the project page, click **Unarchive project**.

## Deleting a project

Admin only. Only available when you are the sole real member.

On the project page, find the **Delete project** section. Type the project name to confirm. Deleting removes the project and all its data permanently, including all expenses and files.

!!! warning
    Deleting a project cannot be undone.

## Settling debts in a project

Use the **Pay someone back** form on the project page to record a payment to another member. See [Settling Up](buddies/settling-up.md) for the full guide, including how the project admin can settle all debts at once.

## The debt diagrams

The project page shows two debt diagrams based on all approved shared expenses:

**Raw debts** — an arrow from each person who owes money to the person they owe it to, with the amount. If two people owe each other, the smaller amount is subtracted and only the net direction shown.

**Simplified** — the minimum number of payments needed to settle everything. Comaney chains debts together where possible. For example, if Alex owes Bailey 10 and Bailey owes Casey 10, the simplified view shows just one arrow: Alex pays Casey 10 directly.

## Reordering your project list

Drag and drop project cards on the Projects page to sort them in the order that suits you. Archived projects always stay at the bottom regardless of your sort order.
