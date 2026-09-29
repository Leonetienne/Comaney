# Offline-Member Merge: Spec vs Implementation Review

Reviewed `merge-spec.md` against the actual implementation and the e2e tests.
Date: 2026-06-25.

Files in scope:
- Services: `buddies/services/archive.py`, `buddies/services/lifecycle.py`, `buddies/services/group.py`, `buddies/services/query.py`, `buddies/services/email.py`
- Views: `buddies/views/buddies.py`, `buddies/views/projects.py`, `buddies/views/main.py`
- Model: `buddies/models/invites.py` (`DummyMergeInvite`)
- Badges: `budget/templatetags/action_badges.py`
- Scheduling: `budget/scheduled_assignment.py`
- Templates: `buddies/templates/buddies/merge_view.html`, `templates/emails/buddy_merge_invite.html`
- Tests: `tests/e2e/buddies/test_merge.py`, `test_merge_request_to_feuser.py`, `test_dummy_merge_into_dummy.py`; `tests/e2e/projects/test_merge_request_to_feuser.py`, `test_dummy_merge_into_dummy.py`; `tests/e2e/profile/test_demo_user.py`

## Overall

The core mechanics are solid and well-tested: conflict-aware share summing, the upfront-payer-becomes-owner case (guarantee #4), no-stale-references, no-duplicate-link, scoped authorization (personal = owner, project = admin), the `already_pending` block for the feuser-request path, badge routing (personal → "buddies", project → "projects"), redirects-to-project, and the demo *sender* block. Authorization is sound — no missing auth checks on the merge/accept/decline/revoke endpoints.

The issues below are mostly **edge cases that bridge the gap between request-time and accept-time**, one **direct spec/implementation contradiction**, and several **test gaps**. None are exploitable account-takeover holes, but #1–#3 are real behavior bugs.

---

## Findings

### 1. [SPEC CONTRADICTION — decide intent] Self-merge is specified as allowed but is actively forbidden

`merge-spec.md:27`:
> "Self-merge is allowed: A user can merge an offline member into themselves. In personal context, this makes expenses no longer be a buddy expense. In project context this behaves as other merges."

The implementation does the **opposite**:
- `request_merge_with_feuser` returns `("self", None)` when `target_feuser.pk == feuser.pk` ([lifecycle.py:336](buddies/services/lifecycle.py:336)).
- `request_group_merge_with_feuser` does the same ([group.py:304](buddies/services/group.py:304)).
- Both views render the error "You cannot merge into yourself." ([buddies.py:307](buddies/views/buddies.py:307), [projects.py:944](buddies/views/projects.py:944)).
- There is **no UI path** to even select yourself: the personal dropdown is built from other buddies (`unified_debts`); the project dropdown excludes self (`feuser_members` filters `m.feuser_id != feuser.pk`).
- No test exercises self-merge.

So a genuinely useful use-case ("I tracked this offline buddy, but those expenses were actually just mine — collapse them into myself so they stop being shared") is unreachable, and the spec's described behavior is contradicted by an explicit guard + error message. Either the spec is stale and should be corrected, or the feature is missing entirely. This is the most important thing to resolve because it's a documented requirement the code refutes.

### 2. [BUG — medium] Accepting a stale merge request silently re-creates a relationship the user already severed

Merge requests live for 7 days. Nothing re-validates the request-time precondition at accept time.

- **Personal:** `accept_merge` calls `_create_link(inviting_feuser, accepting_feuser)` unconditionally ([lifecycle.py:392](buddies/services/lifecycle.py:392)). The spec calls this a "harmless defense-in-depth no-op" (spec:58) — but it is **not** a no-op if the two users un-buddied (`kick_actual`) after the request was sent. Accepting re-links them, re-establishing a buddy connection the user deliberately removed.
- **Project:** `accept_group_dummy_merge` does `BuddyGroupMember.objects.get_or_create(group=group, feuser=accepting_feuser)` ([group.py:358](buddies/services/group.py:358)). If the member **left the project** (or was removed) between request and accept, accepting **re-adds them as a member** of a project they left.

The spec's correctness narrative assumes "the recipient is already connected by construction," but that's only guaranteed at request time, not at accept time.

### 3. [GAP — medium] Archived project is not blocked at merge-accept time

Spec:29: "Archived projects block all merge actions on their dummies." This is enforced in the request views (`project_merge_dummy` checks `project.archived` — [projects.py:916](buddies/views/projects.py:916)) but **not** at accept. `accept_group_dummy_merge` ([group.py:322](buddies/services/group.py:322)) re-adds the member, deletes the dummy member row, and calls `reset_project_assignment_to_equal_shares` with no `project.archived` check. So a request sent before archiving can still mutate an archived project after archiving. (Closely related to #2 — both are missing accept-time re-validation.)

### 4. [DEFENSE-IN-DEPTH + TEST GAP — low/med] No explicit "demo cannot be a merge target" guard

Spec:28: "Demo accounts cannot be merge targets." There is **no** `target_feuser.is_demo` check in `request_merge_with_feuser` or `request_group_merge_with_feuser`. It is only *indirectly* safe because a demo account can't be a buddy or a project member (the invite paths block `invitee_is_demo`), and the merge target must already be one. That invariant holds today, but the rule is asserted with no direct enforcement and **no regression test** ("real user cannot merge a dummy into a demo account"). A future change to how demo accounts enter the social graph would silently violate the spec rule.

### 5. [BUG — low] Misleading audit-note wording for plain dummy→dummy merges

In `merge_dummy_into_dummy`, the participant rows are annotated `"Original participant was: X"` (correct, matches spec:49), but the upfront-payer rows are annotated `"Archived from: X"` ([archive.py:82](buddies/services/archive.py:82)). For a regular "merge offline Bob into offline Bob2" (not an archive), the expense note now reads "Archived from: Bob", which is wrong/confusing — nothing was archived. The method is now general-purpose (spec:49 renamed it from `merge_dummy_into_archive`), so the note text should be merge-neutral and consistent with the participant branch.

### 6. [DEFENSE-IN-DEPTH — low] Service primitives trust the view's scoping

`request_merge_with_feuser` / `request_group_merge_with_feuser` / `merge_dummy_into_dummy_now` / `merge_group_dummy_into_dummy_now` don't re-assert that `dummy` is in the expected scope (e.g. `dummy.owning_group is None` for personal, `dummy.owning_group_id == group.pk` for project) or that `dummy.is_archive is False`. Today every caller is a view that already scopes via `get_object_or_404`, so this is safe, but the service layer is the documented public API (spec "Service-layer primitives") and these are easy invariants to assert cheaply.

### 7. [INFO — low] No accept/decline feedback to the requester

Buddy/group invite flows send "accepted"/"declined" notifications (`send_group_invite_accepted` / `_declined`). Merge requests send none. On accept the dummy simply vanishes from the requester's list (implicit feedback); on decline it just reappears as no-longer-pending. Probably intentional, but worth a conscious decision since it diverges from the sibling flows.

---

## Test gaps

- **Immediate dummy→dummy merge blocked while a request is pending** (spec:30, the `already_pending` branch in `merge_dummy_into_dummy_now` / `merge_group_dummy_into_dummy_now`). Only the *feuser-request* duplicate path is tested (`TestPersonalMergeRequestBlocksDuplicate`, `TestProjectMergeRequestBlocksDuplicate`). The "you have an outstanding request, so the immediate merge is refused" branch has zero coverage.
- **Cross-scope merge impossibility** (spec:25). No test that a `target_key` pointing at a dummy/feuser in another scope is rejected (e.g. personal `merge_dummy` with a `d<id>` of a project dummy, or a project merge targeting a personal dummy). The `get_object_or_404` scoping enforces it but it's untested.
- **Demo as merge target** (spec:28) — see finding #4. No test.
- **Accept-after-unbuddy / accept-after-leave** (findings #2/#3) — would be the regression tests once those are fixed.
- **Upfront-payer conflict in the immediate dummy→dummy path.** The "upfront payer becomes owner, target's stale row absorbed" case (guarantee #4) is only tested on the *request-to-feuser* path (`TestMergeRequestUpfrontPayerBecomesRealOwner`). The immediate dummy→dummy path only tests participant conflict-summing.
- **Audit-trail note** (spec:49). No test asserts the "Original participant was: …" annotation actually lands on the expense after a merge.

---

## Prepared session prompts

Each block below is self-contained — paste it into a fresh session.

### Prompt A — Resolve the self-merge contradiction (do this first; it's a decision)
```
In the Comaney repo, merge-spec.md line 27 states that self-merge is allowed:
"A user can merge an offline member into themselves. In personal context, this
makes expenses no longer be a buddy expense." But the implementation forbids it:
- buddies/services/lifecycle.py request_merge_with_feuser returns ("self", None)
  when target_feuser.pk == feuser.pk
- buddies/services/group.py request_group_merge_with_feuser does the same
- buddies/views/buddies.py:307 and buddies/views/projects.py:944 show
  "You cannot merge into yourself."
- The target dropdowns never include "yourself" (personal uses other buddies;
  project excludes m.feuser_id == feuser.pk).

First tell me which way to reconcile this: (a) the spec is stale — remove the
self-merge claim from merge-spec.md and leave the code as-is, or (b) self-merge
is a real requirement — implement it. Lay out exactly what (b) would require
(personal: convert the dummy's expenses to non-buddy/self-owned and drop the
buddy participation; project: behave like a normal merge into the owner), the
UI changes (adding "Yourself" to the dropdown), and the edge cases, before
writing any code. Add e2e tests for whichever path we choose. Do not commit.
```

### Prompt B — Re-validate merge-request preconditions at accept time
```
In the Comaney repo, accepting a DummyMergeInvite does not re-check the
request-time precondition, so a stale request (up to 7 days old) can re-create
a relationship the user already severed:

- buddies/services/lifecycle.py accept_merge() calls _create_link(inviting_feuser,
  accepting_feuser) unconditionally. If the two users un-buddied (kick_actual)
  after the request was sent, accepting silently re-links them.
- buddies/services/group.py accept_group_dummy_merge() does
  BuddyGroupMember.objects.get_or_create(group=group, feuser=accepting_feuser).
  If the member left or was removed from the project after the request was sent,
  accepting re-adds them as a member.
- accept_group_dummy_merge() also does NOT check project.archived, so a request
  sent before archiving can still mutate an archived project (merge-spec.md:29
  says archived projects block all merge actions).

Decide and implement the correct behavior: accepting a merge request whose
precondition no longer holds (no longer buddies / no longer a member / project
archived) should fail cleanly and show the invalid-request page, rather than
re-establishing the connection or mutating an archived project. The personal
_create_link call should only run if they are still buddies (or be removed if
the precondition is enforced). Add e2e regression tests:
1. personal: A requests merge into B, A and B un-buddy, B accepts -> request is
   rejected, no BuddyLink re-created.
2. project: admin requests merge of a dummy into member M, M leaves the project,
   M accepts -> rejected, M not re-added.
3. project archived after the request is sent -> accept rejected, project
   untouched.
Follow CLAUDE.md test rules (e2e at :8080, time.sleep not WebDriverWait). Do not commit.
```

### Prompt C — Explicit demo-target guard + test
```
In the Comaney repo, merge-spec.md:28 says "Demo accounts cannot be merge
targets," but there is no explicit guard for it. buddies/services/lifecycle.py
request_merge_with_feuser and buddies/services/group.py
request_group_merge_with_feuser only check the SENDER's is_demo, never the
target's. It's currently only indirectly safe because demo accounts can't be
buddies/members. Add an explicit guard: if target_feuser.is_demo, reject the
merge request (new outcome, surfaced as a user-facing error in
buddies/views/buddies.py merge_dummy and buddies/views/projects.py
project_merge_dummy). Add an e2e test in tests/e2e/profile/test_demo_user.py
asserting a real user cannot send a merge request targeting a demo account,
mirroring test_real_user_cannot_invite_demo_as_buddy. Do not commit.
```

### Prompt D — Fix the misleading audit-note wording
```
In the Comaney repo, buddies/services/archive.py merge_dummy_into_dummy()
annotates participant rows with "\nOriginal participant was: {name}" but
annotates upfront-payer expenses with "\nArchived from: {name}"
(archive.py around line 82). This method is now general-purpose (used for any
offline-member -> offline-member merge, not just the Achim Archive), so for a
normal merge the expense note wrongly reads "Archived from: Bob". Make the
upfront-payer annotation merge-neutral and consistent with the participant
branch (e.g. "Originally paid by: {name}" or reuse "Original participant was").
Check whether any test or template relies on the exact "Archived from:" string
first. Add a small test asserting the audit note lands correctly after a
dummy->dummy merge. Do not commit.
```

### Prompt E — Close the merge test gaps
```
In the Comaney repo, add e2e tests for these uncovered merge behaviors
(merge-spec.md). Follow CLAUDE.md test rules (e2e at :8080, ctx fixtures,
time.sleep then assert, run via `pytest -sx <path>`):

1. Immediate dummy->dummy merge is blocked while a merge request is pending for
   that dummy (spec line 30). Seed a DummyMergeInvite for a personal dummy, then
   POST /buddies/dummy/<id>/merge/ with a d<id> target -> expect "pending merge
   request" error and the source dummy still present. Repeat for a project dummy
   via /projects/<id>/dummy/<id>/merge/.
2. Cross-scope merge is rejected (spec line 25): a personal merge_dummy whose
   target_key points at a project dummy (and vice versa) must 302 back without
   merging.
3. Upfront-payer conflict in the immediate dummy->dummy path: source dummy is the
   upfront payer of an expense where the target dummy already has an explicit
   participation row; after merge the target's owner/implicit share must absorb
   correctly and no row may be lost (mirror TestMergeRequestUpfrontPayerBecomesRealOwner
   but for the immediate path).
4. The expense audit note "Original participant was: <name>" is actually written
   after a merge.

Put personal cases under tests/e2e/buddies/ and project cases under
tests/e2e/projects/, matching the existing file layout. Do not commit.
```

### Prompt F — (optional) Harden service-layer scope assertions
```
In the Comaney repo, the merge service primitives trust the calling view's
scoping. Add cheap defensive assertions so they're safe if ever called directly:
- buddies/services/lifecycle.py: request_merge_with_feuser and
  merge_dummy_into_dummy_now should verify the dummy is personal
  (owning_group_id is None) and not is_archive.
- buddies/services/group.py: request_group_merge_with_feuser and
  merge_group_dummy_into_dummy_now should verify dummy.owning_group_id == group.pk
  and not is_archive.
Return a clean error outcome rather than raising where a view would surface it.
Keep it minimal and matching the existing return-tuple convention. Do not commit.
```
