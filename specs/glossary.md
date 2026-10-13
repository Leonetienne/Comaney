# Glossary

| Term | Meaning |
|---|---|
| Feuser | An app user, backed by the custom `FeUser` model (not Django's auth user). |
| Expense | A single money movement record. Has a type, value, owner and optional metadata. "Expense" also names the record in general, whatever its type. |
| Transaction type | One of Expense, Income, Savings deposit, Savings withdrawal. |
| Owner | The feuser recorded as `Expense.owning_feuser`. Only the owner's own category and tags on the expense row count as their classification. |
| Foreign expense | An expense the current feuser does not own but participates in. |
| Participant | A feuser or offline member with a `BuddySpending` row on an expense they do not own, representing their share. |
| Share | A participant's percentage of an expense value. The owner holds the remainder implicitly. |
| Upfront payer | The person who paid the full amount of a shared expense. |
| Expense overlay | A participant's personal category, tags and note for a foreign expense, stored per (expense, feuser). Never stored empty. |
| Category | One label per expense, owned per feuser. |
| Tag | Zero or more labels per expense, owned per feuser. |
| Unclassified expense | An expense missing a category and/or tags from the current feuser's point of view. |
| Settled | The money has actually moved. Unsettled records are upcoming obligations. |
| Deactivated | Hidden from all totals and charts but kept in history. |
| Financial month | A month starting on the feuser's configured start day, optionally in the previous calendar month. |
| Financial year | Twelve financial months labelled by calendar year. |
| Recurring (scheduled) expense | A template from which expense records are generated on a repeat pattern. |
| Occurrence date | The immutable date a generated expense was materialised for. |
| Contact | Another feuser or offline contact you split expenses with outside any project. |
| Offline contact / offline member / dummy | A participant without an account (`DummyUser`). "Offline contact" in personal context, "offline member" in project context. |
| Achim Archive | A special dummy (`is_archive`) that absorbs the history of removed offline members. |
| Project | A shared container of members and expenses (formerly "Buddy Group"). |
| Project admin | The one member of a project allowed to manage it. |
| Solo project | A project with no member other than the admin. |
| Settlement | An expense flagged as a debt payoff between two participants, not real spending. |
| Debtor / creditor | The paying / receiving side of a settlement. |
| Approval (participant) | A participant's check-or-cross consent to their share of an expense. |
| Auto-accept trust | A feuser's per-contact opt-in to accept that contact's entries without confirmation. |
| Merge | Folding an offline member's history into another offline member, a real user, or oneself. |
| Catalog Partnership | A group of feusers whose tags and categories stay synchronised. |
| Partner | Another feuser in the same Catalog Partnership. |
| Onboarding (partnership) | The invitee's wizard mapping their catalog onto the partnership catalog. |
| Dashboard | A named, ordered collection of dashboard cards. |
| Card | A dashboard widget configured by YAML. |
| Query language | The search mini-language used by the expense search and card queries. |
| Personal / Shared mode | Personal counts own expenses in full. Shared counts own and foreign expenses at the feuser's own share. |
| AI provider | A plug-in file implementing one AI service (`claude`, `deepseek`, `local`, community). |
| Shared AI access | AI access configured for the whole instance, limited per user per month. |
| Own AI settings | A feuser's own credentials for the active AI provider, unlimited by Comaney. |
| AI Express | AI-assisted creation of expenses from a description or receipt photo. |
| Sankey Studio | Early access editor that turns a node graph of tags, categories and projects into a Sankey chart. |
| Connector node | A Sankey node with no meaning of its own, used as a wiring hub. |
| Early access | A per-feuser opt-in that unlocks unfinished features. |
| Demo user | A shared public account with restricted capabilities. |
| Second factor | TOTP app, security key (WebAuthn), email code or YubiKey OTP. |
| Primary factor | The second factor asked for first at login. Exactly one per feuser. |
| Recovery code | One global code per feuser that bypasses and removes all second factors. |
| Toast | A transient notification in the bottom-right corner. |
| Stoerer | A persistent reminder banner (partnership onboarding). |
