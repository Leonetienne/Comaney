# TICKET-02 — Missing authorization on buddy-expense upfront payer & participants

**Severity:** High (broken access control: cross-user record creation, IDOR, spam channel)
**Type:** Authorization / IDOR
**Components:** `budget/views/expenses.py` (`_parse_buddy_post`), `budget/views/express.py`
(`confirm` action → `_parse_buddy_item`), `buddies/services/expense.py`
(`BuddyExpenseService.set_buddy_spendings`)

## Summary

When creating or editing a buddy/project expense, the server trusts the numeric
FeUser and DummyUser IDs supplied in the POST body without verifying that those
identities are actually connected to the acting user (a buddy, or a member of the
selected project) or, for dummies, that they belong to the acting user. The web UI
only offers the user's own buddies, but the endpoints accept any ID.

Three concrete abuses follow:

1. **Create an expense owned by an arbitrary victim.** With
   `buddy_upfront_type=feuser` and `buddy_upfront_id=<any active user pk>`, the new
   expense is saved with `owning_feuser = <victim>` and `buddy_approved=False`, and
   an approval-request email is sent to the victim. The title/note/value are
   attacker-controlled. This lets any user plant records in a stranger's account and
   push attacker-worded transactional email at them through the app.

2. **IDOR on `DummyUser`.** With `buddy_upfront_type=dummy` (or a participant of
   `type=dummy`), the code loads `DummyUser.objects.get(pk=uid)` / sets
   `participant_dummy_id = int(p["id"])` with no `owning_feuser=feuser` filter, so
   another user's private offline-buddy record can be attached to the attacker's
   expense.

3. **Add non-connected users / non-members as participants.** `set_buddy_spendings`
   writes `BuddySpending` rows straight from the JSON with no membership check.

## Root cause

`budget/views/expenses.py`, `_parse_buddy_post`:

```python
if upfront_type == "feuser":
    uid = int(post.get("buddy_upfront_id", 0))
    result["upfront_feuser"] = FU.objects.get(pk=uid, is_active=True)   # no buddy/member check
elif upfront_type == "dummy":
    uid = int(post.get("buddy_upfront_id", 0))
    result["upfront_dummy"] = DummyUser.objects.get(pk=uid)             # no owner check (IDOR)
...
result["spendings"] = json.loads(post.get("buddy_spendings_json", "[]"))  # ids never validated
```

`buddies/services/expense.py`, `set_buddy_spendings`:

```python
for p in participants:
    bs = BuddySpending(expense=expense, share_percent=Decimal(str(p["share_percent"])))
    if p["type"] == "feuser":
        bs.participant_feuser_id = int(p["id"])   # arbitrary pk
    else:
        bs.participant_dummy_id = int(p["id"])    # arbitrary pk (foreign dummy)
```

`create_expense`/`expense.save()` then persists `owning_feuser = upfront_feuser`
(`budget/views/expenses.py:297-303`). The express `confirm` path reaches the same
place through `_parse_buddy_item` (`budget/express_service.py:409-452`), which also
resolves `FU.objects.get(pk=upfront_id, is_active=True)` without a connection check.

Note the group path (`_parse_buddy_post`, `mode == "group"`) *does* verify the
project via `members__feuser=feuser`, but the per-participant IDs inside that project
are still unchecked, and `_parse_buddy_item` in express omits even `archived=False`
on its `Project.objects.get(...)`.

### Mitigating factor (do not treat as a fix)

The unified debt view (`buddies/services/query.py:get_all_debts_unified`) only sums
net debt for people who already share a `BuddyLink` or project, so an injected
participant who has no relationship to the victim will not surface a *balance* in the
victim's debt graph. The impact is nonetheless real: records created in a victim's
account (abuse #1), foreign dummy references (abuse #2), unsolicited approval emails,
and pending-approval clutter.

## Proposed fix

Enforce, server-side, that every referenced identity is within the acting user's
authorized set, and reject the whole submission otherwise (mirroring the existing
`result["valid"] = False` pattern):

1. **Upfront FeUser** must be a current buddy of `feuser`, or (group mode) a member
   of the selected project:
   ```python
   from buddies.services import BuddyQueryService
   allowed = {b.pk for b in BuddyQueryService.get_actual_buddies(feuser)}
   if mode == "group" and result["group"]:
       allowed |= set(result["group"].members
                      .filter(feuser__isnull=False)
                      .values_list("feuser_id", flat=True))
   if uid not in allowed:
       result["valid"] = False
   ```
2. **Upfront/participant DummyUser** must be owned by `feuser`, or belong to the
   selected project:
   ```python
   DummyUser.objects.get(pk=uid, owning_feuser=feuser)      # direct
   # or, group mode: dummy is a member of result["group"]
   ```
3. **`set_buddy_spendings`** should validate each participant id against the same
   allowed set before writing rows (add an `allowed_feuser_ids` / `allowed_dummy_ids`
   argument, or have callers pre-validate and pass only vetted rows). Reject unknown
   ids rather than silently dropping, so the caller can surface an error.
4. Apply the identical checks in `budget/express_service.py:_parse_buddy_item`
   (including `archived=False` on the project lookup).

Centralizing this in one validator used by all three entry points (web create, web
edit, express confirm) is preferable to duplicating the logic.

## Regression testing

- **Unit/integration**: for each entry point, POST an expense with
  `buddy_upfront_id` set to a non-buddy user pk and assert the expense is rejected
  (no `Expense` row created, no email sent) — assert `owning_feuser` never becomes a
  stranger.
- **IDOR**: create user A with a DummyUser; as user B, submit an expense referencing
  A's dummy pk as upfront payer and as a participant; assert rejection and that no
  `BuddySpending` row points at A's dummy.
- **Positive path**: a genuine buddy and a genuine project member are still accepted;
  a project dummy is still accepted in group mode.
- **Regression**: express `confirm` with a hand-crafted `preview_json` referencing a
  foreign feuser/dummy is rejected the same way.
