# Offline Member Merge: Feature Specification

## Overview

Every offline member (`DummyUser`) — a direct buddy or a project member who doesn't use Comaney — can be **merged** via a "Merge into..." option in its "..." menu. The merge target is either:

- **another offline member** in the same scope, or
- **an already-linked real user**: an existing direct buddy (personal scope) or an existing project member (project scope).

This fully replaces the old "Invite as user" flow (free-text email, auto-onboarding for strangers). Bringing a brand-new person into the system is now a separate, prior step using the existing generic "invite a buddy" / "invite to project" flows. Only once that person is actually linked can a dummy be merged into them.

Two distinct actions, depending on the target type:

| Target | Action | Approval |
|---|---|---|
| Another offline member | Immediate merge | None — short in-DOM confirm dialog, irreversible |
| An already-linked real user | Merge **request** | Target must accept; sender can revoke first |

---

## Scope rules (if these differ from implementation details below in error, these scope rules are more important)

- **Personal** (direct buddies): only the owning feuser can merge their own dummies. Real-user targets must already satisfy `BuddyQueryService.are_buddies(feuser, target)`.
- **Project**: only the project **admin** can merge a project's dummies (matches all other offline-member management). Real-user targets must already be an existing `ProjectMember` of that project.
- Cross-scope merges are not possible: a personal dummy can never merge into a project dummy/member, and vice versa.
- The special `is_archive=True` "Achim Archive" dummy can be neither source nor target of this feature — it has its own dedicated removal-time merge flow (`BuddyArchiveService.wipe_archive` / the "Remove" action).
- Self-merge is allowed: a user can merge an offline member into themselves via a dedicated "Yourself" entry in the same target dropdown (`target_key="self"`). It is always immediate, in both scopes - there's no second party to ask, so it never goes through the request/accept ceremony. In personal context, every `BuddySpending` row for the dummy is dropped rather than reassigned (the owner's implicit share absorbs it - this is what "no longer a buddy expense" means); upfront-payer expenses still transfer via the existing owner-becomes-real-owner path. In project context it reuses the exact same transfer primitives as a normal merge-into-member request - see the owner-exclusion fix below.
- Demo accounts can initiate dummy-to-dummy merges. Demo accounts cannot be merge targets.
- Archived projects block all merge actions on their dummies, same as add/remove.
- Only one outstanding merge request per source dummy at a time: sending a second request while one is pending is rejected ("already_pending"), and the immediate dummy-into-dummy merge is also blocked while a request is outstanding for that dummy — both to prevent an outgoing request from being silently orphaned out from under its recipient.

---

## Data model (no new models)

Reuses two pre-existing models:

- **`DummyUser`**: scoped via `owning_feuser` XOR `owning_group`, never both.
- **`DummyMergeInvite`**: `inviting_feuser`, `dummy`, `invited_feuser`, `token`, `expires_at` (7 days). Already branches correctly on `dummy.owning_group` for personal vs. project semantics — used unchanged for the "merge request" action in both scopes.

`BuddyOnboardingInvite.dummy` (used only by the removed free-email onboarding fallback) was removed via migration `0015_remove_buddyonboardinginvite_dummy` — confirmed zero live rows had it set before dropping it. `BuddyOnboardingInvite` itself stays: it still powers onboarding invites for direct buddies and project members who aren't registered yet (`BuddyLifecycleService.invite_actual`, `ProjectService.invite_member`, resolved on registration via `complete_onboarding_invites`, called from `feusers/views/auth.py`). Only the third, now-unreachable case the field supported (merge-onboarding for an unregistered stranger) was removed. Two call sites had a dead `dummy__isnull=True` filter left over from before the field removal (`revoke_onboarding_invite`, `BuddyQueryService.pending_onboarding_invites_outgoing`) — `manage.py check` doesn't execute function bodies, so it never catches a `FieldError` like this; found by grepping for every remaining reference after the field removal, not from `check` output.

---

## Service-layer primitives

### Immediate dummy-into-dummy merge

- `BuddyArchiveService.merge_dummy_into_dummy(source, target)` (generalized from the old `merge_dummy_into_archive` — works for any target, not just the archive): transfers `BuddySpending` rows and `upfront_payee_dummy` references. **Conflict-aware**: if target already participates in the same expense, shares are **summed into one row**, never duplicated. Annotates `expense.note` with "Original participant was: X" for an audit trail.
- `BuddyLifecycleService.merge_dummy_into_dummy_now` (personal) / `ProjectService.merge_group_dummy_into_dummy_now` (project): call the above, then migrate the source's recurring (`ScheduledExpense`) assignments — personal via `replace_dummy_in_scheduled` (migrates to target, conflict-summed), project via `reset_project_assignment_to_equal_shares` (matches the existing roster-change convention) — then delete the source dummy.

### Immediate self-merge

- `BuddyArchiveService.merge_dummy_into_self(dummy, feuser)`: drops every `BuddySpending` row for the dummy outright (annotating the same "Original participant was: X" note first) instead of reassigning it - a personal dummy's participations always live on expenses already owned by that same feuser, so reassigning would create an invalid owner-as-participant row. Upfront-payer expenses are unaffected by this and go through the existing `transfer_upfront_payer_to_feuser` unchanged.
- `BuddyLifecycleService.merge_dummy_into_self` (personal): calls the above, clears any `ScheduledExpense` referencing the dummy via `clear_scheduled_assignments` (same blunt reset `kick_dummy` already uses - a removed dummy can't be surgically replaced in a schedule's upfront/participant slot the way a *target* dummy can), then deletes the dummy.
- `ProjectService.merge_group_dummy_into_self` (project): does **not** use `merge_dummy_into_self`. It calls `transfer_upfront_payer_to_feuser` + `transfer_dummy_participation_to_feuser` directly with `admin_feuser` as the target - the same two primitives `accept_group_dummy_merge` uses for a normal merge-into-member - then removes the `ProjectMember` row, deletes the dummy, and resets scheduled spendings.
- **Owner-exclusion fix (applies beyond self-merge too):** `transfer_dummy_participation_to_feuser` now drops a `BuddySpending` row instead of creating it whenever the target already owns that particular expense (`expense.owning_feuser_id == feuser.pk`), mirroring the guard `transfer_upfront_payer_to_feuser` already had. Without this, project self-merge would routinely create an invalid owner-as-participant row whenever the admin already owned one of the dummy's expenses - and the same bug was latent (just rarer) in ordinary merge-into-member requests whenever the chosen target happened to already own one of the dummy's expenses.
- Both self-merge paths are immediate, like dummy-into-dummy - there's no second party to ask, so the request/accept ceremony is skipped entirely. Both are blocked with `"already_pending"` while an outgoing merge request exists for that dummy, same as the dummy-into-dummy path.

### Merge request into a real user (requires acceptance)

- `BuddyLifecycleService.request_merge_with_feuser` / `ProjectService.request_group_merge_with_feuser`: validate scope/self/demo/duplicate rules, create a `DummyMergeInvite`, send via the existing `BuddyEmailService.send_merge_invite` (which already creates a `Notification` row **and** sends the email in one call — this is what drives the navbar bell and the email, with zero new plumbing).
- `BuddyLifecycleService.accept_merge` dispatches to `BuddyGroupService.accept_group_dummy_merge` for project-scoped dummies. Both:
  - Transfer expense history via `BuddyArchiveService.transfer_upfront_payer_to_feuser` (reassigns ownership for expenses where the dummy was the upfront payer; **strips the target's own stale self-participation row** if they already had one on that expense — the expense owner is never an explicit participant) and `transfer_dummy_participation_to_feuser` (same conflict-summing as the dummy-into-dummy case).
  - Personal only: migrate `ScheduledExpense` via `replace_dummy_in_scheduled`.
  - **Project merges do NOT create a `BuddyLink`.** The target is already a project member by construction; merging an offline record must not have the side effect of creating an unrelated personal buddy connection between them and the admin. (Personal merges still call `_create_link`, but it's a no-op there since the precondition guarantees they're already buddies — kept as a harmless defense-in-depth safety net, not a behavior change.)
  - Delete the dummy and the invite.
- `BuddyLifecycleService.revoke_merge_invite`: sender-side cancellation, mirrors the existing `revoke_invite` pattern. Works for both scopes.

---

## Correctness guarantees (each empirically verified, each has a regression test)

1. **No expense loss.** Every expense the merged dummy touched still exists after the merge.
2. **No stale references.** No `BuddySpending` row, `ScheduledExpense.assign_upfront_dummy`, or `assign_spendings_json` entry may reference a dummy after it's deleted.
3. **Conflict-aware share merging.** If both the source and the target already participate in the *same* expense (or recurring schedule), their shares are summed into a single row — never left as two separate rows for the same participant.
4. **Owner-share correctness.** When a dummy that was an expense's upfront payer merges into a feuser who already had an explicit participation row on that same expense, that stale row is removed and the new owner's implicit share absorbs it correctly (e.g. payer's implicit 40% + target's old explicit 30% → target's new implicit owner share is 70%, not 40%).
5. **No unwanted `BuddyLink` creation** from a project-scoped merge.
6. **No duplicate `BuddyGroupMember`/`BuddyLink`** when the target was already linked before accepting (idempotent via `get_or_create` throughout).
7. **No owner-as-participant row.** A merge target who already owns the expense being transferred (always true for personal self-merge; possible for project self-merge or even an ordinary merge-into-member) never ends up with an explicit `BuddySpending` row on their own expense - the row is dropped, not created, and their implicit owner share absorbs it.

---

## UI / entry points

- **My Buddies** (`my_buddies.html`): "Merge into..." in the "..." menu of each offline buddy, opens a `<select>` (optgroups "Offline buddies" / "Buddies", plus a standalone "Yourself" option) built from already-rendered `unified_debts`, no new query needed. "Merge requests you sent" / incoming "Offline record link requests" sections list outstanding invites with Revoke / Accept+Decline.
- **Project settings** (`project_settings.html`, admin section): same pattern using `dummy_members` / `feuser_members`, admin-only, also with a standalone "Yourself" option. "Merge requests sent" (admin) and "Merge requests for you" (any member) sections.
- Target dropdown uses an `f<id>`/`d<id>` prefixed-value convention (matches the existing settlement-form precedent) so one endpoint can dispatch on prefix, plus a third bare `"self"` sentinel value (no id needed - the target is implicitly the requesting feuser) handled before the prefix split.
- "Merge into..." is always shown to non-demo users (admin in project scope), even with zero other dummies/buddies to merge into, since "Yourself" is always a valid target.
- Confirmation: the existing shared `window.confirmDialog()` (in-DOM, irreversible-action pattern), with dynamic wording depending on whether the selected target is a dummy ("Merge X into Y? Irreversible."), yourself ("Merge X into yourself? ... folded into your own account."), or a feuser ("Send a merge request to Y?").

## Badges & notifications

A pending incoming merge request must increment, all simultaneously, with no separate plumbing beyond what already existed:
- The navbar bell (`unread_notification_count`) — via the existing `Notification` row created by `_emit`.
- The relevant sidebar nav badge: personal-scoped → "Manage Buddies"; project-scoped → "Projects" (moved out of the buddies badge to match where the inline UI actually lives).
- The per-project-card badge on `/projects/` (`_project_pending_counts` — this one was missed in the first pass and had to be added separately; it's a different code path from the sidebar badge).

## Redirects

`accept_merge` / `decline_merge` land the user on the **project page** (`projects:project_detail`) when the merged dummy was project-scoped, not on My Buddies — they're already a project member, so that's the natural place to land, not an unrelated personal page.

---

## Wording requirements

A merge request is **not** an invitation — the recipient is, by construction, already connected (already a buddy, or already a project member). All user-facing text must reflect this:

- Never say "invitation" for a merge request — say "merge request" (`invite_invalid.html` / `invite_wrong_account.html` are shared with genuine invite flows and take a `noun` template variable, defaulting to `"invitation"` for those, overridden to `"merge request"` for merge call sites).
- Never say "group" — say "project" (the `Project` model was renamed from `BuddyGroup`; legacy "group" wording must not leak into new copy).
- Must explicitly state the recipient is **already** a member/buddy (counters the inherited "you'll be added" framing from the old stranger-onboarding copy).
- Must **not** claim "you become spending buddies" for a project merge (false — see correctness guarantee #5) or for a personal merge (redundant — they already are).
- Expense-history bullets must attribute the offline entry to its original tracker: `"All shared expenses tracked under {inviting_name}'s 'X (offline member)' are transferred to your account."` — for both personal and project branches.
- Applies identically to: the confirmation page (`merge_view.html`), the email (`buddy_merge_invite.html`), the email subject/message (`BuddyEmailService.send_merge_invite`), and the inline dashboard cards (`my_buddies.html`, `project_settings.html`).

---

## What was removed

- The free-text-email "Invite as user" forms and their views (`send_merge_invite`, `project_send_merge`), replaced by the target-dropdown `merge_dummy` / `project_merge_dummy` views.
- The onboarding-fallback branches (typed email not matching any registered user) from the merge-invite creation methods — no longer reachable, since a merge target is always an already-resolved, already-linked `FeUser`.
- The **entire** legacy `buddies/views/groups.py` (15 view functions: `create_group`, `group_invite_member`, `group_revoke_invite`, `group_remove_member`, `group_add_dummy`, `group_rename_dummy`, `group_archive_wipe`, `group_transfer_admin`, `group_leave`, `group_dissolve`, `group_rename`, `group_picture`, `view_group_invite`, `accept_group_invite`, `decline_group_invite`) and its whole `buddies:groups/...` URL namespace in `urls.py`, plus the orphaned `group_invite_view.html` template.
  - `group_send_merge` (the merge-specific one) was confirmed dead by grep, but turned out to still have a dedicated security test in `test_demo_user.py` — updated to hit the live route instead of being left broken.
  - `view_group_invite`/`accept_group_invite`/`decline_group_invite` were **not actually dead** — `my_buddies.html`'s "Group invitations" card linked to them directly (`BuddyGroupInvite` is just an alias for `ProjectInvite`, so this was genuine parallel routing to the same data, not dead code). Switched that card to the live `projects:view_project_invite` equivalent first, confirmed byte-for-byte equivalent template content, *then* deleted the legacy path.
- Four dead duplicate routes under `buddies:groups/<id>/settle-individual|settle-all/` and `.../expense/<id>/approve-dummy|reject-dummy/` — same underlying view functions as the live `projects:` routes, zero template references on the `buddies:` side.
- Two now-redundant demo-enforcement tests (`test_cannot_invite_via_group_endpoint`, `test_real_user_cannot_invite_demo_to_group`) that only existed to exercise the legacy route — each already had an equivalent test covering the same property via the live `projects:` route.
- `BuddyOnboardingInvite.dummy` (see Data model above).

Deliberately **not** touched: the model/service-level aliases (`BuddyGroup`, `BuddyGroupInvite`, `BuddyGroupMember`, `BuddyGroupService`) — CLAUDE.md documents these as an intentional, ongoing artifact of the Buddy-Groups→Projects rename, distinct from the dead view/URL layer that was actually removed here.
