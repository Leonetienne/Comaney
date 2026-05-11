# User Defaults

When a new user confirms their account, `create_defaults()` in `budget/fixtures.py` is called automatically. It creates the user's starter data:

- **Default categories**: a list of strings in `DEFAULT_CATEGORIES`.
- **Default tags**: a list of strings in `DEFAULT_TAGS`.
- **Default dashboard cards**: a list of YAML card definitions in `DEFAULT_DASHBOARD_CARDS`.

To change what new users get, edit those lists in `budget/fixtures.py`. Order does not matter for categories and tags; duplicates are silently skipped. Dashboard cards are only created if the user has no cards yet.

These defaults only apply to new accounts. Existing users are not affected.
