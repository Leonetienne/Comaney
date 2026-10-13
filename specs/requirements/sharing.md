# Shared Expenses and Settlements

Sources: `buddies/services/expense.py`, `buddies/services/lifecycle.py`,
`buddies/services/settlement.py`, `buddies/services/query.py`, `buddies/debt_utils.py`,
`buddies/models/buddy_spending.py`, `build/js/buddy_expense.js`,
docs `user-manual/buddies/shared-expenses.md`, `settling-up.md`, AGENTS.md.

## Assignment

### Assignment modes
`req~sharing.assign.modes~1`

The expense form shall offer the assignment modes None, Direct Buddy (exactly one direct buddy) and Project (one non-archived project the feuser belongs to).

Covers:
- `feat~sharing~1`

### Participants and shares
`req~sharing.assign.shares~1`

For a shared expense the feuser shall choose the participants (project members may be excluded individually) and their percentage shares via sliders or "Equal shares"; the owner holds the remainder implicitly.

Covers:
- `feat~sharing~1`

### No participants check
`req~sharing.assign.no-participants~1`

If a shared expense is saved with no participant besides the owner, then the system shall block saving with an explanation.

Covers:
- `feat~sharing~1`

### Solo project assignment
`req~sharing.assign.solo~1`

While the selected project is solo, the form shall hide payer and split controls and assign the expense entirely to the feuser.

Covers:
- `feat~sharing~1`

### Upfront payer
`req~sharing.assign.payer~1`

The form shall let the feuser choose who paid upfront, defaulting to themselves: a real buddy or member, or an offline buddy or member.

Covers:
- `feat~sharing~1`

### Real upfront payer
`req~sharing.assign.payer-real~1`

When a feuser records a shared expense with another real user as upfront payer, the system shall create the expense in that user's account, keep it out of the creator's own expense list, and require the payer's approval ("Did you pay for this?") unless the payer trusts the creator; the form shall say which applies before saving.

Covers:
- `feat~sharing~1`

### Offline upfront payer
`req~sharing.assign.payer-offline~1`

When a feuser records a shared expense with an offline buddy or member as upfront payer, the system shall keep it out of the feuser's own expense list and show it on the Buddy Expenses page; inside a project it shall require the admin's confirmation on behalf of the offline member.

Covers:
- `feat~sharing~1`

### Participant notification
`req~sharing.notify~1`

When a feuser is added to, changed on or removed from a shared expense, or set as its upfront payer, the system shall notify them under the matching notification type.

Covers:
- `feat~sharing~1`

## Approvals

### Did you pay for this
`req~sharing.approve.payer~1`

When the designated real upfront payer approves an expense recorded for them, the system shall move it into their expense list and count it in balances; when they reject it, the system shall delete it and notify its creator.

Covers:
- `feat~sharing~1`

### Participant consent
`req~sharing.approve.participant~1`

The system shall let each real participant mark their share approved or rejected, shown as a check or cross per participant, and notify the owner of the decision.

Covers:
- `feat~sharing~1`

### Consent change window
`req~sharing.approve.window~1`

The system shall let a participant change a rejection at any time but revoke an approval only within 24 hours of their first decision.

Covers:
- `feat~sharing~1`

### Approval reset on material edit
`req~sharing.approve.reset~1`

When the owner edits a shared expense and changes its title, value, participants or any share, the system shall reset all participants' decisions to neutral; edits of payee, note, category or date shall keep them.

Covers:
- `feat~sharing~1`

### Reset notice
`req~sharing.approve.reset-notice~1`

When decisions are reset, the update email shall tell only participants who had approved before that their approval was reset.

Covers:
- `feat~sharing~1`

## Settlements

### Settlement record
`req~sharing.settle.record~1`

The system shall record a settlement as an expense flagged as settlement, owned by the debtor, settled, and pending until the creditor confirms; balances shall clear only after confirmation.

Covers:
- `feat~sharing~1`

### Pay someone back
`req~sharing.settle.direct~1`

The "Pay someone back" form shall let a feuser pick a creditor, prefill the amount they owe, accept any amount of at least 0.01 (partial or voluntary), and confirm in a dialog reminding them to actually send the money.

Covers:
- `feat~sharing~1`

### Offline creditor
`req~sharing.settle.offline-creditor~1`

When a feuser settles with their own offline buddy, the system shall confirm the settlement automatically.

Covers:
- `feat~sharing~1`

### Payments by offline buddies
`req~sharing.settle.offline-debtor~1`

The system shall let a feuser record a payment from their offline buddy to themselves, and a project admin record payments from offline members, via "Who's paying".

Covers:
- `feat~sharing~1`

### Creditor review
`req~sharing.settle.review~1`

When a real creditor confirms receipt, the system shall approve the settlement and book a matching "Settlement received from <debtor>" income for the creditor; when they reject it, the system shall delete the settlement and notify the debtor.

Covers:
- `feat~sharing~1`

### Only creditor confirms
`req~sharing.settle.only-creditor~1`

If anyone other than the creditor (or the project admin for an offline creditor) tries to confirm a settlement, then the system shall refuse it.

Covers:
- `feat~sharing~1`

Tags: Security

### Settlement cancellation
`req~sharing.settle.cancel~1`

When the debtor deletes a settlement that is still pending, the system shall delete it and notify the real creditor.

Covers:
- `feat~sharing~1`

### Settlements are not spending
`req~sharing.settle.not-spending~1`

The system shall never show settlements in "Did you pay for this?" and never treat them as unclassified.

Covers:
- `feat~sharing~1`

### Settle entire project
`req~sharing.settle.project-all~1`

When the project admin confirms "Settle entire project" after a summary, the system shall create one settlement per pair of the simplified debt list and email all members; each creditor (or the admin for offline creditors) must still confirm.

Covers:
- `feat~sharing~1`

### No debts
`req~sharing.settle.nothing~1`

If there are no outstanding debts, then the system shall create no settlement and say "No outstanding debts to settle."

Covers:
- `feat~sharing~1`

### Admin confirms for offline members
`req~sharing.settle.admin-offline~1`

The project admin shall see and decide "Confirm expenses for offline members" and "Confirm paybacks to offline members".

Covers:
- `feat~sharing~1`

## Debts

### Balance computation
`req~sharing.debt.balance~1`

The system shall compute each pair's balance from all approved shared expenses and confirmed settlements over all time, netting opposite debts.

Covers:
- `feat~sharing~1`

### Debt simplification
`req~sharing.debt.simplify~1`

The system shall derive a simplified list of transfers that settles all net balances of a project with few payments, by greedily matching largest debtors with largest creditors.

Covers:
- `feat~sharing~1`

### Spending breakdown
`req~sharing.debt.breakdown~1`

The project spending breakdown shall attribute each expense's upfront payment to its payer and move settled amounts from creditor to debtor.

Covers:
- `feat~sharing~1`
