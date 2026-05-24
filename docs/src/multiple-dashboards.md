# Multiple Dashboards

Each user can maintain several named dashboards. Every dashboard is an independent collection of dashboard cards. A tab bar at the top of the dashboard page lets you switch between them.

---

## Data Model

### `Dashboard` (new table: `budget_dashboard`)

| Field | Type | Notes |
|-------|------|-------|
| `uid` | `BigAutoField` (PK) | Auto-increment |
| `owning_feuser` | FK → `FeUser` CASCADE | Ownership check on every request |
| `title` | `CharField(128)` | Display name, editable after creation |
| `sorting` | `IntegerField(default=0)` | User-defined order; lower = leftmost |
| `created_at` | `DateTimeField(auto_now_add)` | |
| `last_mod` | `DateTimeField` | Updated on every save |

### `DashboardCard` (modified)

New field added:

| Field | Type | Notes |
|-------|------|-------|
| `dashboard` | FK → `Dashboard` CASCADE | Every card belongs to exactly one dashboard |

---

## URLs

### Page URLs

| Pattern | Name | Behaviour |
|---------|------|-----------|
| `/budget/` | `budget:dashboard` | Redirect to the user's first dashboard |
| `/budget/dash/<int:uid>/` | `budget:dashboard_detail` | Render a specific dashboard (ownership enforced) |

"First dashboard" = lowest `sorting`, ties broken by lowest `uid`.

### Dashboard API (session auth)

| Method & path | Name | Description |
|---------------|------|-------------|
| `GET /budget/dashboards/` | `budget:dashboards_api` | List all dashboards, ordered |
| `POST /budget/dashboards/` | `budget:dashboards_api` | Create a new dashboard |
| `PATCH /budget/dashboards/<uid>/` | `budget:dashboard_detail_api` | Rename dashboard |
| `DELETE /budget/dashboards/<uid>/` | `budget:dashboard_detail_api` | Delete dashboard + its cards (blocked if only one left → 409) |
| `POST /budget/dashboards/reorder/` | `budget:dashboards_reorder` | Bulk-reorder; body: `{"order": [id…]}` |

### Modified Card APIs

| Change | Detail |
|--------|--------|
| `GET /budget/dashboard/cards/` | Add required `?dashboard_id=<uid>` filter |
| `POST /budget/dashboard/cards/` | Body must include `"dashboard_id": <uid>` |
| `PATCH /budget/dashboard/cards/<uid>/` | Optional `"dashboard_id": <new_uid>` moves card to another dashboard |
| `POST /budget/dashboard/cards/reset/` | Body accepts `"dashboard_id"`. Allowed only for the user's **first** dashboard (409 otherwise) |

---

## `window.DASHBOARD_CONFIG` (template → JS)

```js
window.DASHBOARD_CONFIG = {
    // existing fields
    currency, year, month, mode,
    urlCards,      // /budget/dashboard/cards/?dashboard_id=<uid>
    urlReorder,    // /budget/dashboard/cards/reorder/
    urlPresets,    // /budget/dashboard/cards/presets/
    urlReset,      // /budget/dashboard/cards/reset/

    // new fields
    dashboardId:         <current dashboard uid>,
    isFirstDashboard:    true|false,  // controls reset button visibility
    urlDashboards:       "/budget/dashboards/",
    urlDashboardsReorder: "/budget/dashboards/reorder/",
    dashboards: [
        { id, title, sorting, url },  // ordered list for rendering tabs
        …
    ],
};
```

---

## UI — Desktop

### Tab bar layout

```
← [ Dashboard 1 ] [ Dashboard 2 ] [ My Budget ] →    [+]
```

- Lives between the period nav and the card grid.
- Scrollable horizontally when too wide (CSS `overflow-x: auto`; scrollbar hidden via `::-webkit-scrollbar` trick so it stays visually clean).
- `[+]` button is always at the far right, outside the scrollable area.

### Tab interactions

| Interaction | Result |
|-------------|--------|
| Click tab | Navigate to that dashboard (full page nav, period params preserved) |
| Double-click tab title | Tab title becomes an inline text input; Enter or blur → PATCH title → update |
| Drag tab (on tab itself, not on a card) | Reorder tabs; persisted via `POST /budget/dashboards/reorder/` on drop |
| Click `×` on active tab | Delete confirmation prompt; blocked (button disabled) if only one dashboard remains |
| Click `[+]` | Inline input + submit appear to the right of the tab bar; submit → POST → navigate to new dashboard |

### Drag card onto a tab (desktop)

While dragging a card over the tab bar:
- After ~400 ms hover over a tab, it highlights as a drop target.
- Dropping the card there moves it to that dashboard (PATCH `dashboard_id`).
- Card disappears from the current grid and is visible on the target dashboard.

---

## UI — Mobile

### Normal navigation

- **Swipe left/right** on the card grid to move between dashboards (touch events).
- An **expandable dashboard selector** button (e.g. `≡ Dashboard name ▾`) near the top opens a bottom sheet or inline dropdown that shows all dashboards. From here you can:
  - Jump to any dashboard.
  - Create a new dashboard (input + submit inside the panel).
  - Delete the current dashboard (with confirmation; blocked if only one).
- The expandable selector is **not** a drag-and-drop target.

### Moving a card between dashboards on mobile

During a touch-drag of a card:
- Dragging to the **left edge** (<15 % of screen width) switches to the previous dashboard.
- Dragging to the **right edge** (>85 % of screen width) switches to the next dashboard.
- Both edge zones are visually highlighted during drag.
- Dropping the card after a dashboard switch sends the card to the new dashboard.

---

## Migration

A single Django migration handles the schema change and back-fills existing data.

### Steps (within one migration)

1. **Create** the `budget_dashboard` table.
2. **Add** `dashboard_id` as a nullable FK on `budget_dashboardcard`.
3. **`RunPython`**: for every `FeUser` that has at least one `DashboardCard` and no `Dashboard` yet:
   - Create one `Dashboard(title="Dashboard", sorting=0)`.
   - Set `dashboard_id` on all their `DashboardCard` rows.
4. **`AlterField`**: make `dashboard_id` non-nullable (safe because step 3 filled every row).

Users with no cards and no dashboard get their first dashboard created by `create_defaults()` (see below).

---

## Fixtures (`budget/fixtures/`)

`create_defaults(feuser)` (in `budget/fixtures/__init__.py`) now:

1. For each entry in `DEFAULT_USER_DASHBOARDS` (`budget/fixtures/dashboards.py`), creates (or gets) a `Dashboard(owning_feuser=feuser, title=..., sorting=<iteration index>)`. Today there is one entry, `"main"`, equivalent to the old hardcoded `Dashboard(title="Dashboard", sorting=0)`.
2. For that dashboard, creates the cards listed in its `cards` key, resolved against `PREDEFINED_DASHBOARD_CARDS` (`budget/fixtures/dashboard_cards.py`) -- a card-key allowlist, not the full preset catalog. Cards not listed there can still exist as presets without being given to new users.

Because the FK is required, `bulk_create` receives the dashboard instance directly. This is the first case of an FK relation between initial user records created in a single `create_defaults` call.

---

## Export (account ZIP)

| File | Change |
|------|--------|
| `dashboards.csv` | **New**: all `Dashboard` rows for the user (all concrete fields except `owning_feuser`). |
| `dashboard_cards.csv` | Now includes `dashboard_id` column (automatically included because it is a concrete FK field handled by `_write_model_csv`). |

---

## Demo Users

No additional restrictions. Creating, renaming, and deleting dashboards is a display preference with no effect on other users or the user's identity/credentials.

---

## Reset Dashboard

- The reset button (reset cards to defaults) is visible **only** on the user's first dashboard (lowest `sorting`, ties by lowest `uid`).
- On all other dashboards the button is hidden.
- Reset deletes all cards on the first dashboard and recreates the 10 default cards there. Other dashboards are untouched.

---

## Implementation Checklist

- [ ] `Dashboard` model + migration (schema + data back-fill + make NOT NULL)
- [ ] `DashboardCard.dashboard` FK
- [ ] `/budget/` redirect view
- [ ] `/budget/dash/<uid>/` view (ownership check)
- [ ] Dashboard CRUD API (`dashboards_api`, `dashboard_detail_api`, `dashboards_reorder`)
- [ ] Update card APIs: `dashboard_id` filter/param, move-between-dashboards PATCH
- [ ] Update `cards_reset_api` to enforce first-dashboard-only
- [ ] Update `DASHBOARD_CONFIG` in template
- [ ] Tab bar UI (scroll, create inline, double-click rename, × delete, tab drag-reorder)
- [ ] Card drag-onto-tab (desktop)
- [ ] Mobile swipe navigation + expandable selector
- [ ] Mobile edge-drag card move between dashboards
- [ ] Update `create_defaults()` in `fixtures/`
- [ ] Update account ZIP export (`dashboards.csv`, `dashboard_id` in `dashboard_cards.csv`)
- [ ] Tests: unit tests for model/API; E2E test for tab creation + card move
