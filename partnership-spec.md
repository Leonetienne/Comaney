# Catalog Partnership: Feature Specification

## Overview

A **CatalogPartnership** is a group of FeUsers who share a synchronized set of tags and categories. Any mutation (create, rename, delete) to a tag or category by any partner propagates instantly to all other partners. A user can belong to **at most one** partnership at a time.

The partnership is distinct from the buddy/project relationship but requires at least one mutual connection (BuddyLink or shared Project membership) between every member and the group. If that last connection dissolves, the member is auto-removed.

---

## Data Model

### New: `buddies/models.py` (or a new `buddies/models_partnership.py`)

```python
class CatalogPartnership(models.Model):
    uid = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)

class CatalogPartnershipMembership(models.Model):
    partnership = models.ForeignKey(
        CatalogPartnership, on_delete=models.CASCADE, related_name="memberships"
    )
    feuser = models.OneToOneField(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="catalog_membership"
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    onboarding_complete = models.BooleanField(default=False)

    class Meta:
        unique_together = [("partnership", "feuser")]

class CatalogPartnershipInvite(models.Model):
    partnership = models.ForeignKey(
        CatalogPartnership, on_delete=models.CASCADE, related_name="invites"
    )
    inviter = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="partnership_invites_sent"
    )
    invitee_email = models.EmailField(db_index=True)
    token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted = models.BooleanField(null=True, default=None)  # None=pending, True=accepted, False=declined
```

### Modified: `feusers/models.py`

Add notification preference field:
```python
notify_partnership_changes = models.BooleanField(default=True)
```

### Tag/Category propagation

Tags and categories remain **user-owned** (`owning_feuser` FK stays). The sync service replicates mutations to all partners after each change. No schema change needed on `Tag` or `Category`.

---

## Constraints

- A user can be in at most one partnership (enforced by `OneToOneField` on `CatalogPartnershipMembership.feuser`).
- An invite can only be sent to a user who shares at least one BuddyLink or Project with the inviter.
- An invite can only be sent if the invitee is **not already in a partnership**.
- If a partnership drops to 1 member, it is dissolved (the last `CatalogPartnershipMembership` is deleted along with the `CatalogPartnership`).
- Auto-removal: if a member loses all mutual connections (BuddyLink and Project) to every other member of the partnership, they are removed. Check is triggered on `BuddyLink` delete and `ProjectMembership` delete signals.

---

## Invite Flow

### Entry points

1. **Buddy profile/detail page**: "Invite as partner" button, visible only if the buddy is a real FeUser (not a dummy), is not already your partner (show "Partner" pill instead), and is not already in any other partnership.
2. **Project member list** (admin only): same button per real FeUser member, same visibility rules.

Both entry points are identical after the button click.

### Invite action

1. Show a **confirmation modal** explaining what a partnership is:
   > "A Catalog Partnership syncs your tags and categories with [name]. Any tag or category either of you creates, renames, or deletes will instantly apply to both accounts. To complete the setup, [name] will need to go through a short onboarding wizard."
   Buttons: "Send invite", "Cancel".
2. On confirm: create `CatalogPartnershipInvite`. If the inviter has no partnership yet, also create a new `CatalogPartnership` and add the inviter as a member (`onboarding_complete=True` — the inviter is the master and needs no onboarding).
3. Send invite email to invitee with a link: `/buddies/partnership/accept/<token>/`.
4. Show in-app notification badge on the invitee's "Tags & Categories" sidebar item.
5. Send in-app notification to invitee: "You have been invited to a Catalog Partnership" (class: `partnership_changes`).

---

## Onboarding Wizard (invitee-side, multi-step)

Triggered when the invitee visits `/buddies/partnership/accept/<token>/` or clicks the banner.

The master's catalog is the **canonical source of truth** throughout. The invitee's catalog is rewritten to match it.

### Wizard state persistence (browser)

Wizard progress is stored in `localStorage` under key `partnership_onboarding_<invite_token>`. Each step serializes the current mapping decisions. Closing the modal or navigating away preserves state. When the user re-opens the wizard (via stoerer or notification), the stored state is rehydrated and they land on the step they left.

State is keyed to the invite token so it survives page reloads and browser restarts. It is cleared on successful apply or on "I don't want a partnership".

Because the **master's catalog can change while the invitee is mid-onboarding** (a partner adds new tags between sessions), the wizard always re-fetches the current master catalog fresh on open and reconciles it against stored state:
- Rows with stored decisions are restored as-is.
- Tags/categories the master added since last open appear as new unresolved rows.
- Tags/categories the master deleted since last open are silently removed from the table (and their stored decision discarded).

### Step 1: Explanation

> "You have been invited to join a Catalog Partnership with [inviter name]. This means your tags and categories will be merged into [inviter]'s catalog. Going forward, any change either of you makes will apply to all partners.
>
> Before this can happen, we need to map your existing tags and categories to [inviter]'s. This takes about a minute."

**Buttons:**
- **Next** — proceed to step 2
- **Continue later** — dismiss modal; partnership remains pending; persistent stoerer shown on all pages; progress saved to localStorage
- **I don't want a partnership** — decline: clears localStorage state, deletes `CatalogPartnershipInvite`, removes invitee from partnership. Sends email to inviter: "Your partnership invitation was declined." Sends in-app notification to inviter.

**X button** in the modal header acts identically to "Continue later".

Closing the modal (X, Continue later, clicking outside) does NOT destroy the partnership. The stoerer brings them back.

### Persistent stoerer (banner)

Shown on **all pages** (not just tags/categories) to the invitee while `onboarding_complete=False`. Styled prominently (e.g. full-width yellow bar at top of content area):

> "⚠ You have a pending Catalog Partnership setup. [Complete setup →]"

### Step 2: Tag migration

**Header:** "Map your tags to [inviter]'s catalog"

**Instructions:** "For each of your tags that doesn't exist in [inviter]'s catalog, choose which of their tags it maps to — or check DROP to remove it from your existing expenses."

**Table layout (one row per unmatched source tag):**

| Your tag | → Target tag (dropdown of master's tags) | DROP (checkbox) |
|----------|------------------------------------------|-----------------|

- Tags with an **exact title match** in the master's catalog are pre-resolved and shown as a non-editable "auto-matched" row (greyed out, no action needed).
- Unmatched tags need either a target selected or DROP checked. Submission is blocked until every unmatched row has one or the other.
- **"Take a guess ✦" button**: calls the AI service with the tag mapping prompt (see AI section). Pre-fills all unmatched rows with suggested targets; user can still adjust. Show spinner; show error if budget exceeded.
- **X button / "Continue later"**: saves current decisions to localStorage, closes modal.

**Warning lists** shown below the table (live-updating as the user fills in rows):

- **"Not yet decided"** (amber): lists the invitee's tags that have neither a target selected nor DROP checked.
- **"Not yet in your catalog"** (blue/info): lists the master's tags that no row currently maps to. These will be added to the invitee's catalog as new empty tags after apply — shown as informational, not blocking.

### Step 3: Category migration

Identical layout, logic, X/Continue later, and warning lists to step 2, but for categories.

### Step 4: Confirmation

> "Ready to apply. Here's what will happen:
> - X tags will be remapped on your expenses
> - Y tags will be dropped from your expenses
> - Z categories will be remapped
> - W categories will be dropped
> [Apply and finish] [Back] [Continue later]"

### On apply

1. Rewrite all of the invitee's existing expenses: replace source tags/categories with mapped targets, remove dropped ones.
2. Delete all of the invitee's tags/categories that are not in the master's catalog.
3. Copy the master's full tag/category catalog to the invitee (create matching `Tag`/`Category` objects with `owning_feuser=invitee`).
4. Set `CatalogPartnershipMembership.onboarding_complete = True`.
5. Remove stoerer.
6. Send in-app notification + email to inviter: "Your partnership invitation was accepted."
7. Send in-app notification to all other existing partners: "A new partner is in the house!"

---

## Ongoing Sync

After onboarding completes, every tag/category mutation by any partner propagates to all others.

### Service: `buddies/services/partnership.py`

```python
def sync_tag_create(tag, actor_feuser): ...
def sync_tag_rename(tag, new_title, actor_feuser): ...
def sync_tag_delete(tag, actor_feuser): ...
# same three for Category
```

Each function:
1. Looks up all other `CatalogPartnershipMembership` records for the same partnership.
2. Applies the equivalent mutation to each partner's own tag/category objects.
3. Skips partners whose `onboarding_complete=False` (they haven't merged yet — their catalog is still diverged).

Conflict resolution: **last-write-wins**. These are labels, not financial records.

---

## Breaking Up

### Leave (voluntary)

- Button "Leave partnership" on the Tags & Categories page (partner list section).
- Confirmation modal: "You will keep your current tags and categories. Syncing will stop. Your expenses are not affected."
- On confirm: delete their `CatalogPartnershipMembership`. If partnership drops to 1 member, dissolve `CatalogPartnership` too.
- Notify all remaining partners: "A partner has left." (in-app + email per `notify_someones_partnership_changes`).

### Kick (by any partner)

- "Kick" button per partner in the partner list (any member can kick any other).
- Confirmation modal: "This will remove [name] from the partnership. They will keep their current catalog but will no longer sync."
- On confirm: delete their membership. Same dissolution check.
- Send in-app notification + email to kicked user: "You have been removed from the Catalog Partnership." (respects `notify_own_partnership_changes`).
- Notify remaining partners: "A partner has been kicked." (in-app + email per `notify_someones_partnership_changes`).

### Auto-removal (connection lost)

Triggered by `post_delete` signal on `BuddyLink` and `ProjectMembership`.

Check: does the departing member still share at least one BuddyLink or Project with **any** other member of their partnership? If not: auto-remove them (same flow as kick, but different notification copy).

Notification to remaining partners: "A partner was removed because they are no longer connected to any of you." (in-app + email per `notify_someones_partnership_changes`).

### Account deletion

Handled by the existing cascade on `FeUser`. `CatalogPartnershipMembership.feuser` has `on_delete=CASCADE`, so the membership is removed automatically. The dissolution check (drop to 1 member) must be triggered post-delete via signal.

---

## Catalog Page Changes

### Warning banner

When the user is in a partnership with `onboarding_complete=True`, show a persistent info banner at the top of the Tags and the Categories pages:

> "You are in a Catalog Partnership. Changes you make here apply to all your partners too."

### Deletion confirmation dialog

When a user in a partnership attempts to delete a tag or category, the confirmation dialog copy must include:

> "This will also delete this [tag/category] for all your partners."

### Partner list (below the tag/category lists)

Show a section "Catalog Partners":

For each `CatalogPartnershipMembership` in the same partnership (excluding self):
- Profile picture (or initials fallback)
- First + last name
- Partner since: `joined_at` formatted as "since DD.MM.YYYY"
- Status pill: green "Complete" or yellow "Onboarding"
- "Kick" button (opens confirmation modal)

Below the list: "Leave partnership" button (opens confirmation modal).

---

## Reusable Action Badge (Sidebar)

A small red circle with a count, rendered next to a sidebar menu item when there are pending actions of a given type.

### Template tag

```python
# budget/templatetags/action_badges.py
@register.inclusion_tag("partials/action_badge.html")
def action_badge(feuser, badge_type):
    count = _count_actions(feuser, badge_type)
    return {"count": count}
```

`_count_actions(feuser, badge_type)` is a registry-style dispatcher:

```python
_BADGE_COUNTERS = {}

def register_badge(badge_type):
    def decorator(fn):
        _BADGE_COUNTERS[badge_type] = fn
        return fn
    return decorator

def _count_actions(feuser, badge_type):
    fn = _BADGE_COUNTERS.get(badge_type)
    return fn(feuser) if fn else 0
```

Initial registration in `buddies/partnership_badges.py`:

```python
@register_badge("partnership")
def _count_partnership_actions(feuser):
    # pending invites where this user is invitee
    return CatalogPartnershipInvite.objects.filter(
        invitee_email=feuser.email, accepted=None
    ).count()
```

### Template partial `partials/action_badge.html`

```html
{% if count %}<span class="action-badge">{{ count }}</span>{% endif %}
```

### Sidebar usage (`budget_base.html`)

```html
<li class="{% if active_nav == 'categories_tags' %}active{% endif %}">
    <a href="...">Tags & Categories {% action_badge current_feuser "partnership" %}</a>
</li>
```

---

## In-App Notifications (Tags & Categories page)

When the user visits the Tags & Categories page and has a pending partnership invite (`CatalogPartnershipInvite` with their email and `accepted=None`), show a dismissible notification card at the top:

> "[Inviter name] has invited you to a Catalog Partnership. [Set up now →]"

---

## Notification Classes

Two new `FeUser` preference fields. Add both to the notification settings page as separate toggles:

```python
notify_own_partnership_changes = models.BooleanField(default=True)
notify_someones_partnership_changes = models.BooleanField(default=True)
```

- `notify_own_partnership_changes`: events that directly affect **you** (invite received, you were kicked, your invite was accepted/declined).
- `notify_someones_partnership_changes`: events happening to **others** in your partnership (a partner joined, left, was kicked, was auto-removed).

Both also respect the global `email_notifications` flag.

### Event emails

| Trigger | Recipient(s) | Preference gate | Subject line |
|---------|-------------|-----------------|--------------|
| Invite sent | Invitee | `notify_own_partnership_changes` | "You've been invited to a Catalog Partnership" |
| Invite accepted | Inviter | `notify_own_partnership_changes` | "Your Catalog Partnership invitation was accepted" |
| Invite declined | Inviter | `notify_own_partnership_changes` | "Your Catalog Partnership invitation was declined" |
| New partner joined | All existing partners | `notify_someones_partnership_changes` | "A new partner is in the house!" |
| Partner kicked | Kicked user | `notify_own_partnership_changes` | "You have been removed from a Catalog Partnership" |
| Partner kicked | Remaining partners | `notify_someones_partnership_changes` | "A partner has been removed from your Catalog Partnership" |
| Partner left | Remaining partners | `notify_someones_partnership_changes` | "A partner has left your Catalog Partnership" |
| Partner auto-removed (lost connection) | Remaining partners | `notify_someones_partnership_changes` | "A partner was removed — no mutual connection remaining" |

---

## AI Integration: Tag Mapping

### Agent abstraction

Replace `_call_claude` with a provider-agnostic `_call_agent` in `budget/express_service.py`. The function takes an `AgentConfig` dataclass so future providers (OpenAI, Gemini, local models, etc.) can be added without touching call sites.

```python
from dataclasses import dataclass
from typing import Callable

@dataclass
class AgentConfig:
    provider: str          # "claude" | "openai" | ...
    api_key: str
    model: str | None = None
    max_tokens: int = 1024
    # extend with provider-specific fields as needed

def _call_agent(
    config: AgentConfig,
    system_prompt: str,
    messages: list[dict],
) -> str:
    """Dispatch to the right provider. Returns raw text response."""
    if config.provider == "claude":
        return _call_claude_impl(config, system_prompt, messages)
    raise ValueError(f"Unsupported agent provider: {config.provider!r}")

def _call_claude_impl(config: AgentConfig, system_prompt: str, messages: list[dict]) -> str:
    # current _call_claude implementation moved here
    ...
```

A helper `_default_agent_config(feuser) -> AgentConfig` resolves the user's own key or falls back to the trial key, identical to the current `_trial_state` logic.

The existing smart-create flow calls `_call_agent(_default_agent_config(feuser), _SMART_CREATE_SYSTEM, messages)` — no behaviour change.

### Partnership AI service (`buddies/services/partnership_ai.py`)

```python
_TAG_MAPPING_SYSTEM = """
You are a tag migration assistant. Given a list of source tags and a list of
target tags, suggest the best 1-to-1 or N-to-1 mapping. Source tags that have
no reasonable match should be mapped to null (the user will drop them).
Respond only with a JSON object: {"mappings": [{"source": "...", "target": "..." | null}, ...]}.
"""

def suggest_tag_mappings(feuser, source_tags: list[str], target_tags: list[str]) -> list[dict]:
    """Returns list of {source, target|None} dicts. Raises AIBudgetExceededError on overage."""
    config = _default_agent_config(feuser)
    messages = [{"role": "user", "content": f"Source tags: {source_tags}\nTarget tags: {target_tags}"}]
    result = _call_agent(config, _TAG_MAPPING_SYSTEM, messages)
    return json.loads(result)["mappings"]
```

Same function shape for categories. Show error in the wizard UI if `AIBudgetExceededError` is raised (same error display pattern as express creation).

---

## Tests to Add

### Unit tests (`tests/unit/`)

- `test_partnership_constraints.py`
  - A user cannot join a second partnership (model-level enforcement)
  - Partnership with 1 member is dissolved after the second member leaves
  - `_count_partnership_actions` returns correct count for pending invites
  - `suggest_tag_mappings` parses AI response correctly

- `test_partnership_sync.py`
  - `sync_tag_create` creates matching tag for all `onboarding_complete=True` partners
  - `sync_tag_create` skips partners with `onboarding_complete=False`
  - `sync_tag_rename` renames the tag on all partners
  - `sync_tag_delete` deletes the tag on all partners
  - Same three for categories

- `test_partnership_auto_remove.py`
  - Member is auto-removed when their last BuddyLink to every partner is deleted
  - Member is NOT auto-removed if they still share a Project with at least one partner
  - Dissolution triggers when auto-remove leaves partnership at size 1

### E2E tests (`tests/e2e/buddies/`)

- `test_partnership_invite.py`
  - Happy path: invite buddy, accept, complete onboarding, verify tag sync
  - "Invite as partner" button is hidden if invitee is already in a partnership
  - "Partner" pill is shown on buddy who is already the user's partner
  - Badge appears on "Tags & Categories" sidebar item after invite is sent
  - Badge disappears after invite is accepted/declined

- `test_partnership_onboarding.py`
  - Happy path: tag migration rows pre-filled with exact matches; mismatches require action
  - "Take a guess ✦" pre-fills unmatched rows; user can override
  - Submit is blocked if any unmatched row has neither target nor DROP checked
  - "Later" dismisses wizard but shows persistent stoerer
  - "I don't want a partnership" sends decline email and removes stoerer

- `test_partnership_sync_ui.py`
  - After onboarding: partner A creates a tag; verify it appears in partner B's tag list
  - After onboarding: partner A renames a tag; verify it is renamed for partner B
  - After onboarding: partner A deletes a tag; verify it is gone for partner B
  - Warning banner is visible on Tags and Categories pages for both partners
  - Deletion confirmation dialog includes partner warning copy

- `test_partnership_dissolution.py`
  - Happy path: leave partnership via "Leave partnership" button; partner list updates
  - Kick: any partner can kick another via the kick button in the partner list
  - After leaving: sync no longer propagates (create a tag, verify it does NOT appear on former partner)
  - After last connection deleted: member is auto-removed; remaining partners see notification

- `test_partnership_notifications.py`
  - Invite email is sent to invitee
  - Acceptance email is sent to inviter
  - Decline email is sent to inviter
  - "New partner" notification sent to all existing partners on acceptance
  - "Partner kicked" notification sent to kicked user and remaining partners
  - "Partner left" notification sent to remaining partners
  - All above are suppressed if `notify_partnership_changes=False`

### Pentesting / security tests

- `test_partnership_security.py`
  - A non-partner cannot call the sync endpoints for another user's partnership
  - A user cannot invite someone to a partnership without a mutual connection (returns 403)
  - A user cannot accept an invite token that was not addressed to their email
  - A user cannot skip the onboarding steps by posting directly to the apply endpoint
  - Manipulating `onboarding_complete` via API without completing the wizard is rejected
  - A non-admin project member cannot use the group-member invite button (UI hidden; POST rejected)
  - A user cannot join a second partnership via a direct POST to the accept endpoint
  - CSRF protection is present on all partnership mutation endpoints

---

## Open Questions (resolve before implementation)

1. **Multi-partner invite ordering**: when the partnership already has 3+ members and a new person is invited, which member's catalog is the master? Proposed: the current catalog state (all members already in sync) is the master. The new invitee conforms to any existing member's catalog (they are identical).

2. **Invite from group (non-buddy)**: the invitee may not have a direct BuddyLink with the inviter but shares a project. The auto-remove signal must check both BuddyLink and ProjectMembership for any connection to any partner — not just to the inviter.

3. **Pending onboarding + sync**: if a partner is in state `onboarding_complete=False` and an existing partner creates a new tag, the new tag is NOT synced to the pending partner. When the pending partner completes onboarding, they re-snapshot the master's catalog at that moment, picking up any changes. This avoids partial-state corruption.
