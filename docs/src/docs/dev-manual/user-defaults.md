# User Defaults

When a new user confirms their account, `create_defaults()` in `budget/fixtures/__init__.py` is called automatically. It creates the user's starter data from a few declarative files, one per data model:

- **Default categories**: a list of strings in `DEFAULT_CATEGORIES` (`budget/fixtures/categories.py`).
- **Default tags**: a list of strings in `DEFAULT_TAGS` (`budget/fixtures/tags.py`).
- **Dashboard card catalog**: every predefined card, keyed by a slug, in `PREDEFINED_DASHBOARD_CARDS` (`budget/fixtures/dashboard_cards.py`). This is the full set shown as presets in the "new card" dialog.
- **Default dashboards**: which dashboard(s), and which *subset* of the catalog above, a new user actually receives, in `DEFAULT_USER_DASHBOARDS` (`budget/fixtures/dashboards.py`).

To change what new users get, edit `DEFAULT_CATEGORIES` / `DEFAULT_TAGS` directly. Order does not matter for categories and tags; duplicates are silently skipped. Dashboards and cards are only created if the user has no dashboard cards yet.

## Catalog vs. defaults

`PREDEFINED_DASHBOARD_CARDS` and `DEFAULT_USER_DASHBOARDS` are deliberately separate:

- Adding a new entry to `PREDEFINED_DASHBOARD_CARDS` makes it available as a preset in the "new card" dialog for everyone, but does **not** give it to new users.
- Only card keys listed under a dashboard's `cards` in `DEFAULT_USER_DASHBOARDS` are auto-created on signup.

This lets you publish a new preset (for example, a gauge card) without it showing up unsolicited on every new account. `budget/fixtures/dashboard_cards.py` ships one such catalog-only example: `income_spent_gauge`, a `type: gauge` preset that is not part of `DEFAULT_USER_DASHBOARDS`.

```python
# dashboards.py
DEFAULT_USER_DASHBOARDS = {
    "main": {
        "title": "Dashboard",
        "cards": ["income", "savings", ...],   # keys into PREDEFINED_DASHBOARD_CARDS
    },
}
```

`Dashboard.sorting` follows the iteration order of `DEFAULT_USER_DASHBOARDS`; adding a second entry gives new users a second pre-populated dashboard.

The "reset dashboard to defaults" button (`cards_reset_api`) resets the user's first dashboard to the card set of the first entry in `DEFAULT_USER_DASHBOARDS`, the same one `create_defaults()` seeds on signup.

These defaults only apply to new accounts. Existing users are not affected.
