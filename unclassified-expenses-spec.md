# Feature Spec: Unclassified Expenses

## 1. Purpose

Give a feuser a single place to find every expense that is missing a category and/or
tags (their own expenses, plus foreign expenses they participate in where their own
overlay classification is missing), fix each one inline, or let AI suggest the
fix, without leaving the page.

## 2. Terminology

This glossary must be added to `CLAUDE.md` verbatim (see section 10). Terms already
documented elsewhere in CLAUDE.md are repeated here only for completeness of the
glossary block; do not duplicate their full explanations.

- **feuser**: An app user, backed by the custom `FeUser` model (not
  `django.contrib.auth.User`). Session key `request.session["feuser_id"]`.
- **expense**: A single spending record (`budget.Expense`). Always has exactly one
  `owning_feuser` (the "owner").
- **owner / owning expense**: The feuser recorded as `Expense.owning_feuser`. Only
  the owner's own `category`/`tags` fields on the `Expense` row itself count as
  "their" classification.
- **foreign expense**: An expense the current feuser did not create (is not the
  `owning_feuser`) but is a **participant** on, via a `BuddySpending` row.
- **participant**: A feuser (or offline dummy) with a `BuddySpending` row against an
  expense they don't own, representing their share of that spend.
- **expense overlay** (`ExpenseDataOverlay`): A participant's *personal* category,
  tags, and note for a foreign expense, stored separately from the expense itself
  (one row per `(expense, feuser)`). Lets each participant classify a shared
  expense their own way without affecting the owner's or other participants'
  classification.
- **category**: A single label (`budget.Category`) an expense can have. Owned
  per-feuser (each feuser has their own category list); one category per expense
  (or per overlay).
- **tag(s)**: Zero or more labels (`budget.Tag`) an expense can have. Owned
  per-feuser; a plain many-to-many relation on `Expense` (or on the overlay).
- **direct buddy**: Another feuser (or offline dummy) you split expenses with
  directly, outside of any project.
- **project**: A shared group of members (`buddies.Project`) that expenses can
  belong to; formerly called "Buddy Group".
- **project member**: A feuser or dummy belonging to a project
  (`buddies.ProjectMember`).
- **partner**: Another feuser in the same Catalog Partnership as you (shared
  category/tag catalog mapping) - distinct from "buddy"; unrelated to this feature.
- **unclassified expense** (this feature): An expense that is missing classification
  from the current feuser's point of view. Precisely:
  - **Own expense**: `owning_feuser == current feuser` and (`category` is null OR it
    has zero `tags`).
  - **Foreign expense**: current feuser is a participant (has a `BuddySpending` row,
    `participant_feuser = current feuser`) and their own `ExpenseDataOverlay` for
    that expense either doesn't exist, or exists with no `category` and zero
    `tags`. The owner's own classification of that same expense is irrelevant to
    this check - it is evaluated purely from the current feuser's overlay.
  - Settlement expenses (`is_buddies_settlement=True`) are never unclassified -
    excluded outright regardless of category/tags state.
  - Expenses in archived projects are still included (archiving blocks mutation of
    the expense itself, not its classification).

## 3. Nav entry + action badge

Add a new sidebar link under the existing "Budget" section in
[templates/budget_base.html](templates/budget_base.html), directly below "Categories
& Tags" (after line 22, before "Add Expense"):

```html
<li class="{% if active_nav == 'unclassified' %}active{% endif %}">
    <a href="{% url 'budget:unclassified_list' %}">Unclassified Expenses {% action_badge current_feuser "unclassified_expenses" %}</a>
</li>
```

Register the counter in
[budget/templatetags/action_badges.py](budget/templatetags/action_badges.py) using
the existing `@register_badge` mechanism (see `_count_buddy_expense_actions` for a
similar multi-source count):

```python
@register_badge("unclassified_expenses")
def _count_unclassified_actions(feuser) -> int:
    return count_unclassified_expenses(feuser)
```

`count_unclassified_expenses(feuser)` lives in the new `budget/unclassified.py`
module (section 4) so the same counting logic backs both the badge and the page
itself - never duplicate the query.

## 4. Query logic (`budget/unclassified.py`, new module)

New module, mirroring the shape of `budget/dashboard_cards.py` /
`budget/express_service.py` (pure query/data-shaping helpers, no view logic):

```python
def get_unclassified_rows(feuser) -> list[UnclassifiedRow]:
    """
    Returns one row per unclassified expense (own or foreign), newest first.
    """

def count_unclassified_expenses(feuser) -> int:
    """Same filtering as get_unclassified_rows, but just the count."""
```

`UnclassifiedRow` is a small dataclass (or dict) with at least:
- `expense_uid`
- `kind`: `"own"` or `"foreign"`
- `title`, `date_due` (or whatever date field `Expense` exposes for display)
- `category_uid` / `category_title` (from `Expense.category` if own, else from the
  feuser's `ExpenseDataOverlay.category` if foreign; `None` if missing)
- `tag_uids` / `tag_titles` (same own-vs-overlay split)
- `problem`: one of `"Category missing"`, `"Tags missing"`,
  `"Category and Tags missing"` - derived from which of the two are missing
- for foreign rows only: `owner_category_title`, `owner_tag_titles` (the *owner's*
  own classification of the expense, read-only context for the AI prompt and for
  display as a hint - see section 6.2)

Implementation notes:
- Own-side query: `Expense.objects.filter(owning_feuser=feuser, is_buddies_settlement=False).filter(Q(category__isnull=True) | Q(tags__isnull=True)).distinct()` (or equivalent that correctly captures "zero tags", since `tags__isnull=True` on an M2M means "no related Tag row" - verify this filters correctly per Django M2M semantics, i.e. use `.annotate(Count("tags"))` and filter `tag_count=0` if `tags__isnull` doesn't behave as expected for M2M).
- Foreign-side query: expenses where `feuser` has a `BuddySpending` row and
  `owning_feuser != feuser`, `is_buddies_settlement=False`, left-joined against
  `ExpenseDataOverlay` filtered to `feuser=feuser`; missing overlay, or overlay
  present but empty category and empty tags.
- This is a fourth place implementing the "own vs overlay" visibility split
  documented in CLAUDE.md alongside `_tag_q`/`_cat_q`, `visible_tag_titles`, and
  `dashboard_cards._compute_chart` - update that CLAUDE.md paragraph to mention it
  (section 10).

## 5. Page: `/budget/unclassified/`

New view `unclassified_list(request)` in `budget/views/unclassified.py` (new file,
following the `budget/views/expenses.py` / `budget/views/express.py` split),
`@feuser_required`, `active_nav = "unclassified"`. URL name
`budget:unclassified_list`.

Renders a single, unpaginated list (per product decision - the list shrinks as
items are resolved, and the app's scale doesn't need paging here). Columns:

| Title | Problem | Category | Tags | Actions |
|---|---|---|---|---|

- **Title**: expense title, plain text. For a foreign expense, additionally show a
  small "(shared)" or similar visual hint so the user understands why editing it
  opens a different, lighter-weight form (parallel to how `expense_edit_overlay`
  already frames itself as a "lite editor").
- **Problem**: one of the three fixed strings from section 4, plain text/badge.
  Reflects the **last-saved** state only; a pending unsaved edit or an unsaved AI
  suggestion does not change this column's text, even though the Category/Tags
  cells beside it show the new pending values. The row disappears from the list
  entirely (removed from the DOM immediately, no reload) once a save resolves it,
  per section 6.5.
- **Category**: see section 6.1.
- **Tags**: see section 6.2.
- **Actions**: "Edit" button/link (hidden while the row has unsaved changes, per
  section 6.4) plus "Let AI solve" / "Let AI retry" (section 7).

At the bottom of the list: "Let AI resolve all" (section 8) and "Save all"
(section 9, visible only when at least one row is dirty).

If there are zero unclassified expenses, show a plain empty-state message (e.g.
"Nothing to classify - you're all caught up.") and hide the bottom action buttons.

### Data handed to the page

Server-render, once, as JSON embedded in the page (same approach as
`_build_catalog` for AI Express - a small trusted payload, not a paginated API):
- The row list from `get_unclassified_rows` (including `owner_category_title`
  /`owner_tag_titles` for foreign rows, needed client-side only for display, not
  editing).
- The current feuser's full category catalog: `[{uid, title}, ...]`.
- The current feuser's full tag catalog: `[{uid, title}, ...]`.

This mirrors `_build_catalog` in `budget/express_service.py`; do not introduce a
second catalog-building helper - factor a shared `feuser_category_tag_catalog(feuser)`
helper in `budget/express_service.py` (or a neutral shared module) and have both
call sites use it, if the existing `_build_catalog` can't be reused as-is (it also
serializes projects/buddies, which this feature doesn't need).

## 6. Inline editing

Each row tracks, client-side (Alpine.js, consistent with `expenses.js`), three
pieces of state per field (category, tags): the **last-saved value** (from the
server payload, or updated after a successful save/AI-apply), the **current
(possibly edited) value**, and whether it's **dirty** (current != last-saved for
either field on that row).

### 6.1 Category cell

- **View mode**: plain text - the category title, or an empty/dash placeholder if
  missing.
- **Click** anywhere in the cell: swap to a `<select>` populated from the feuser's
  category catalog (plus a blank/"none" option), pre-selected to the current
  value.
- **On change**: the cell's value updates immediately (client-side only); the row
  becomes dirty (see 6.4). The `<select>` stays open/rendered - there is no need to
  blur out of a dropdown the way there is for the tags combobox, since a `<select>`
  has no free-text state to reconcile. (Optionally revert to plain-text display
  after `change` fires, matching the tags cell's blur behavior, for visual
  consistency - implementer's choice, but stay consistent between rows.)
- Changing back to the original last-saved value clears dirty for that field (and
  the row overall, if the other field is also clean).

### 6.2 Tags cell

- **View mode**: comma-separated tag titles as plain text (compact - this is
  explicitly meant to take little horizontal space).
- **Click** anywhere in the cell: swap to a combobox:
  - Each current tag renders as a small pill (with an `x`/click-to-remove).
  - Followed by a text `<input>` for typing.
  - As the user types, filter the feuser's tag catalog by substring match
    (case-insensitive) against title, and show matches in a dropdown beneath the
    input (client-side filtering against the embedded catalog from section 5 - no
    new autocomplete endpoint needed, catalogs are small per-feuser lists).
  - Clicking a suggestion adds it as a pill (if not already present) and clears the
    input text, keeping focus in the input for further typing.
  - There is no existing combobox component in the codebase to reuse (confirmed:
    tag entry elsewhere in the app is checkbox-list based) - this is new Alpine
    markup/JS, scoped to this page's own JS (new file
    `build/js/unclassified.js`, bundled the same way as `expenses.js` via
    `build/build-assets.sh`; do not bolt it onto `expenses.js`).
- **Blur** (clicking outside the cell): convert back to the comma-separated
  plain-text view, reflecting the current pill set. If the pill set differs from
  the last-saved tag set, the row becomes dirty.
- For foreign rows, the combobox only ever offers/accepts tags from the current
  feuser's own catalog (never the owner's) - consistent with overlay semantics.

### 6.3 Unsaved-change highlight

New CSS custom properties in
[build/scss/_variables.scss](build/scss/_variables.scss), added alongside the
existing palette (not reusing `--sav-dep-bg`/`--sav-dep-fg`, which already mean the
"Savings Deposit" expense-type color elsewhere in the app - reusing them here would
visually collide with that unrelated meaning). Reuse the *same color values* so the
app's palette doesn't grow, just under new, correctly-named variables:

```scss
// light theme, in the :root block
--unsaved-bg: #cce5ff;
--unsaved-fg: #004085;
```
```scss
// dark theme override block
--unsaved-bg: #0d2a4a;
--unsaved-fg: #7ec8f7;
```

Apply `background: var(--unsaved-bg); color: var(--unsaved-fg);` to any
Category/Tags cell whose field is currently dirty (pending unsaved edit, whether
from manual editing or an unapplied AI suggestion).

### 6.4 Edit / Revert / Save buttons

- While a row is clean (no dirty fields): show only "Edit" (and "Let AI solve") in
  the Actions cell.
- The instant a row becomes dirty (either field edited, or an AI suggestion has
  been produced but not yet saved): hide "Edit", show "Revert" and "Save" in its
  place. "Let AI solve" stays visible, relabeled "Let AI retry" once at least one
  AI suggestion has been generated for that row (label persists across manual
  edits too, once it's flipped once - only resets to "Let AI solve" after a
  successful save, since after saving there's nothing to "retry" until the row
  becomes unclassified again, which can't happen without a further edit).
- **Revert**: discard all pending client-side edits for that row, resetting
  category/tags back to the last-saved values; row becomes clean again ("Edit"
  reappears, "Revert"/"Save" disappear, highlight clears).
- **Save**: POST the row's current category/tag values to the server (section
  6.5). Disable both buttons while the request is in flight.

### 6.5 Saving a single row

New endpoint: `POST /budget/unclassified/<int:uid>/save/`, view
`unclassified_save(request, uid)`, `@feuser_required`. `uid` is always the
`Expense.uid`. Body (JSON): `{"category_uid": int|null, "tag_uids": [int, ...]}`.

Server determines routing the same way `expense_edit`/`expense_edit_overlay` do
today, transparently to the client (no separate "own" vs "foreign" endpoint):
- If `Expense.objects.filter(uid=uid, owning_feuser=feuser).exists()`: update that
  `Expense`'s `category`/`tags` directly, call `expense.update_lastmod()`-equivalent
  if one exists for `Expense` (check `Expense`/`OwnedModel` for a lastmod hook; if
  none exists on `Expense`, skip - don't invent one for this feature).
- Else: look up the feuser's `BuddySpending` row for that expense (404 if none -
  not a participant), then call the existing `upsert_overlay(expense, feuser,
  category, tags, note=<preserve existing overlay note, if any>)` from
  `budget/services.py` - reuse it as-is, don't reimplement overlay upsert logic.

Validate `category_uid` belongs to the feuser's own categories and every
`tag_uids` entry belongs to the feuser's own tags (400 on any foreign id - this is
a security boundary, not just a UX nicety).

Response: `{"category_title": ..., "tag_titles": [...], "problem": "..." | null}`
(`problem: null` means fully classified now). Client behavior on success:
- Update that row's last-saved state to the just-saved values.
- If `problem` is `null`, remove the row from the DOM and decrement the nav badge
  count in place (re-render the `{% action_badge %}` partial via a small
  targeted DOM update, or simply re-fetch/recompute count client-side - whichever
  is simpler given the existing badge markup is server-rendered HTML, not a JS
  component; a full page reload is also acceptable here since it's a single
  low-frequency action, but a live DOM removal is preferred for a snappier feel).
- If `problem` is non-null (user only fixed one of two missing fields and chose to
  save anyway), the row stays, "Problem" cell text updates to the new value, row
  returns to clean state ("Edit" reappears).

## 7. "Let AI solve" / "Let AI retry" (single row)

New endpoint: `POST /budget/unclassified/<int:uid>/ai-solve/`, view
`unclassified_ai_solve(request, uid)`, `@feuser_required`. Does **not** persist
anything - it only returns a suggestion for the client to apply as a pending
(dirty, unsaved) edit, same as if the user had typed it in manually.

New module `budget/unclassified_ai.py`, structured exactly like
`budget/dashboard_card_ai.py`: owns the system prompt text and context assembly,
talks to the AI exclusively through `AIService`, never constructs an Anthropic
client directly.

Add `prompt_unclassified_solve(self, system_prompt, expense_summary) -> dict` to
`AIService` (`budget/ai_service.py`), following the exact convention of
`prompt_dashboard_card_yaml`/`prompt_partnership_mapping`: build an `AgentConfig`,
call `self._call_for_json(config, system_prompt, messages, feature="unclassified_solve")`,
pull the expected key(s) out of the parsed envelope. **This automatically bills
usage the same way every other AI feature does** (`_call_for_json` always calls
`_record_usage`, success or failed-after-repair, per the existing shared
implementation - do not bypass `AIService` or call `_record_usage` manually).
Confirm after implementation, with a quick manual check or unit test, that
calling this new method actually decrements/records against the feuser's trial
or personal budget like the other features do - this is a hard requirement, not
just a suggestion.

### System prompt contents

Assembled per-request in `budget/unclassified_ai.py`, following
`dashboard_card_ai.py`'s pattern of static instructions + dynamic context blocks:

1. Static instructions block (cacheable): explains the task - "given this
   expense's metadata and the user's category/tag catalog, suggest values only
   for whichever of category/tags is currently missing; never suggest a
   category/tag that isn't in the provided catalog (closed catalog - if nothing
   fits well, leave that field's suggestion empty/null rather than forcing a
   bad match)." Response format: strict JSON envelope matching the app's
   AI conventions, e.g.
   ```json
   {"result": "good", "category_uid": 5, "tag_uids": [2, 7]}
   ```
   with `category_uid`/`tag_uids` omitted or null when that field wasn't missing
   or no good match was found. Follow the same "no prose, first/last char must be
   {/}" formatting rules used in `_SYSTEM_INSTRUCTIONS` in `dashboard_card_ai.py`.
2. Dynamic context block, per request:
   - `feuser.ai_custom_instructions` (if set) - same pattern as
     `dashboard_card_ai._build_catalog_block` / `express_service`'s custom
     instructions wiring.
   - The feuser's full category catalog and tag catalog (`{uid, title}` pairs -
     reuse the same catalog-building helper as section 5, don't rebuild it a
     third time).
   - The expense's full metadata: title, value, date, payee, note, type, project
     (if any).
   - Only which of category/tags is missing (tell the AI explicitly which
     field(s) to fill, don't make it re-derive that from the catalog).
   - **If this is a foreign expense**: also include the *owner's* original
     category title and tag titles for this same expense (read-only context, not
     something the AI can pick from unless it also happens to exist in the
     current feuser's own catalog) - this is what helps the AI map "the owner
     called this 'Groceries'" onto the current feuser's own equivalently-named or
     similar category/tag.

### Client behavior

- Clicking "Let AI solve"/"Let AI retry" blocks the whole view (full-page overlay
  with a spinner/"Thinking..." message, all buttons on the page disabled) for the
  duration of the request - there is no existing full-page-blocking component in
  the app to reuse (the dashboard's AI-assist only disables its own trigger
  button while waiting); build a small reusable blocking-overlay partial for this
  page.
- On success: apply the returned `category_uid`/`tag_uids` (resolved to
  titles from the already-embedded catalog) as the row's new pending (dirty)
  values, exactly as if the user had edited them manually - triggers the same
  highlight (6.3) and Edit->Revert/Save swap (6.4), and flips the button label to
  "Let AI retry".
- On `AIBudgetExceededError`/`AIAuthenticationError`/`AIBillingError`
  /`AITransientError` (the typed exceptions `AIService` raises): unblock the view
  and show a clear, non-technical error message (per this project's plain-language
  docs convention) appropriate to the error - e.g. budget exceeded should say so
  plainly rather than a generic failure message.

## 8. "Let AI resolve all"

Client-side only (no new bulk-AI endpoint) - loops the section 7 endpoint once per
row, sequentially:
- Skip rows that are already dirty with a pending (unsaved) AI suggestion (don't
  clobber a suggestion the user hasn't reviewed yet) - but do include rows that
  are clean, and rows the user has manually edited (a manual edit isn't an "AI
  suggestion", so still fair game; though note if a row is dirty from a *manual*
  edit, running AI on it will overwrite that manual edit with the AI's guess -
  this is acceptable since the user explicitly asked to resolve *all* remaining
  problems).
- Actually, simplest and least surprising: only run AI resolve-all against rows
  that are still fully clean (not dirty at all, from any source) - so it never
  overwrites anything the user has touched, manually or via a prior single-row
  "Let AI solve". Rows already dirty are left untouched, and the user can still
  hit their own per-row "Let AI solve"/"Save" individually.
- The whole view stays blocked for the entire sequential run (not just per
  request) - show progress, e.g. "Resolving 3 of 12...".
- Each row updates live (per section 7's client behavior) as its response comes
  back, before moving to the next row.
- If any row's call raises a billing/budget/transient error, stop the loop
  immediately (don't keep burning further AI calls into a broken key), unblock the
  view, report how many rows were completed vs. remaining, and surface the same
  clear error message as the single-row case.

## 9. "Save all"

New endpoint: `POST /budget/unclassified/save-all/`, view
`unclassified_save_all(request)`, `@feuser_required`. Only visible/clickable when
at least one row is currently dirty. Body: a JSON list of
`{"expense_uid": int, "category_uid": int|null, "tag_uids": [int, ...]}`, one entry
per dirty row (client collects them all).

Server: same per-row validation and own-vs-overlay routing as section 6.5's
single-row save, applied to every entry in one request/transaction (wrap in
`transaction.atomic()` - all-or-nothing is simplest and avoids partial-failure UX
complexity; if any single entry fails validation, e.g. a `category_uid` that
doesn't belong to the feuser, fail the whole request with a 400 identifying which
entry, and apply nothing).

Response: per-row results the same shape as the single-row save endpoint (list of
`{expense_uid, category_title, tag_titles, problem}`). Client applies each result
exactly as section 6.5's single-row success path (remove row if `problem` is
null, otherwise update and clear dirty), and hides "Save all" once no dirty rows
remain.

## 10. CLAUDE.md updates required alongside this feature

Per CLAUDE.md's own rule ("Updating a feature: keep CLAUDE.md, AGENTS.md, and
docs/src/ in sync"), the implementer must:

1. Add the glossary block from section 2 above to CLAUDE.md (a new "## Glossary"
   section near the top, or folded into "Key conventions" - implementer's
   judgment on placement, but it must exist as a scannable list).
2. Add a "**Unclassified Expenses**" paragraph under "Key conventions", following
   the existing prose style (see the "Participant approvals" or "Scheduled
   expenses" paragraphs for the expected level of detail/precision), covering: the
   own-vs-overlay unclassified definition, the settlement/archived-project
   exclusions, the new `budget/unclassified.py` / `budget/unclassified_ai.py`
   split, and the fact that this is a fourth place implementing the
   own-vs-overlay visibility rule (update the existing sentence in the "Query
   parser" paragraph that currently says "exists in three shapes" to say "four
   shapes", naming this feature's module alongside the other three).
3. Add the new `AIService.prompt_unclassified_solve` method to the "AI calling
   framework" paragraph's implicit list of `prompt_*` methods if that paragraph
   enumerates them (check current wording at implementation time).
4. Add a new user-manual page under `docs/src/docs/user-manual/` documenting the
   Unclassified Expenses page for end users - plain, non-technical language (this
   codebase's docs are written for everyday users, not developers): what an
   "unclassified expense" is in user terms (e.g. "an expense missing a category or
   tags"), how to fix one inline, what "Let AI solve" does, and that AI usage
   here counts against their AI usage limit like other AI features in the app.

## 11. Tests

Per CLAUDE.md ("New functional features or fixes: must add tests"):

- **Unit** (`tests/unit/`): the unclassified-detection query logic in
  `budget/unclassified.py` - own expense missing category only, missing tags
  only, missing both, fully classified (excluded); foreign expense with no
  overlay, empty overlay, overlay with only category, overlay with only tags,
  overlay fully set (excluded); settlement expenses always excluded regardless of
  state; archived-project expenses still included. Also unit-test the AI prompt
  assembly in `budget/unclassified_ai.py` (system prompt contains custom
  instructions, catalog, and - for foreign expenses - the owner's original
  classification) with a stubbed/fake AI call, not a live one.
- **E2E** (Selenium, live stack): nav badge count matches the number of
  unclassified expenses and updates after resolving one; inline category
  dropdown edit -> Save removes the row; inline tags combobox edit (typing,
  selecting a suggestion, removing a pill) -> Save removes the row; Edit button
  is hidden while dirty and reappears after Revert; foreign-expense row's Edit
  button opens the overlay editor, not the full expense editor, and returns to
  this page on save (via the existing `back` param); "Let AI solve" populates
  and highlights the row without saving, flips to "Let AI retry", and "Save"
  afterward removes the row; "Save all" only appears once a row is dirty and
  clears all dirty rows in one action; AI usage via this feature is reflected in
  the feuser's trial/usage budget (reuse whatever assertion pattern existing AI
  e2e tests use, e.g. in `test_express_creation.py` or similar, for checking
  usage was billed).

Provide the exact `pytest` command(s) to run the new tests when handing off
implementation (per this project's own convention), e.g.:
```
venv/bin/pytest tests/unit/test_unclassified.py -v | tee logfile.log
pytest tests/e2e/expenses/test_unclassified.py -v | tee logfile.log
```
(adjust paths to wherever the implementer actually places these files, following
the existing `tests/unit/` / `tests/e2e/` directory conventions.)

## 12. Explicitly out of scope

- No dashboard card type for this (nav badge only, per product decision).
- No pagination (single page, per product decision).
- No ability to create a brand-new category/tag from this page - category/tag
  values offered are strictly the feuser's existing catalog (creation happens on
  the existing Categories & Tags page only).
- No bulk AI endpoint - "Let AI resolve all" is a sequential client-side loop over
  the existing single-row AI endpoint, not a new batched-AI-call server feature.
- Demo users: no special restriction needed - classifying expenses (setting
  category/tags) is not one of the blocked demo actions (doesn't send email,
  doesn't modify another user's data beyond the always-allowed
  overlay-on-your-own-participation case, doesn't alter identity/credentials).
  Confirm this against the demo-user rules in CLAUDE.md at implementation time in
  case AI usage itself needs demo-specific budget handling (`special_ai_trial_budget`,
  already mentioned in CLAUDE.md for AI Express) - reuse whatever pattern AI
  Express already applies for demo users' AI usage, don't invent a new one.
