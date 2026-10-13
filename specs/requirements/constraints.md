# Design Constraints

Sources: AGENTS.md, `docs/src/docs/dev-manual/`.

### Technology stack
`req~constraints.stack~1`

The system shall be built with Python 3.12, Django, Gunicorn, WhiteNoise and MariaDB, with SCSS and JavaScript bundled by esbuild through `build/build-assets.sh` in a container, never with npm on the host.

Covers:
- `feat~constraints~1`

### Theming via custom properties
`req~constraints.css-vars~1`

Themeable styles shall use CSS custom properties only, never SCSS variables.

Rationale:
SCSS variables are fixed at build time and break dark mode.

Covers:
- `feat~constraints~1`

### Custom user model
`req~constraints.feuser~1`

Authentication shall use the custom `FeUser` model with `feuser_id` in the session, never `django.contrib.auth` users, `request.user`, `login()` or `@login_required`.

Covers:
- `feat~constraints~1`

### Expense factory
`req~constraints.expense-factory~1`

Code shall create expenses only through `create_expense()`, never by instantiating `Expense` directly.

Covers:
- `feat~constraints~1`

### Single AI entry point
`req~constraints.ai-service~1`

Every AI feature shall talk to the AI only through `AIService` and a `prompt_*` method; feature modules own their prompt text and payload validation; `AIService` contains no feature prompt text and touches no domain model.

Covers:
- `feat~constraints~1`

### Django-free providers
`req~constraints.ai-providers~1`

Files in `ai_providers/` shall not import Django or touch the database, settings, email or trial flag, shall read options only via `config()` and the passed user config, raise only typed errors, never put secrets in messages or logs, and keep vendor SDK imports in their own provider file.

Covers:
- `feat~constraints~1`

### Registry-driven second factors
`req~constraints.twofa-registry~1`

Login, removal, profile, rename and test code for second factors shall work off the factor registry and never branch on a method name; a new method shall need only a model, a registration call, a setup view and a login verifier entry.

Covers:
- `feat~constraints~1`

### Shared catalog for AI Express
`req~constraints.express-catalog~1`

The AI Express catalog, prompt block selection and payload validation shall reuse the exact project and buddy lists built for the request's assignment widget, never a second query.

Rationale:
Member order is not deterministic across queries; separate queries would desynchronise index references.

Covers:
- `feat~constraints~1`

### Project mutations update lastmod
`req~constraints.project-lastmod~1`

Every code path that mutates a project shall call `project.update_lastmod()`.

Covers:
- `feat~constraints~1`

### Pure algorithms
`req~constraints.pure-algorithms~1`

Debt simplification, Sankey routing, AI availability resolution and AI providers shall be importable without Django so they can be unit tested in isolation.

Covers:
- `feat~constraints~1`

### Test conventions
`req~constraints.test-conventions~1`

End-to-end tests shall wait with `time.sleep()` rather than `WebDriverWait`, run with `-v` only (never `-x`), and guard AI-dependent tests with `helpers.ai_unavailable()` instead of `pytest.skip`.

Covers:
- `feat~constraints~1`

### Comment style
`req~constraints.comments~1`

Code comments shall be the exception, describe the current state and the reason, avoid history, filler words and dashes as sentence separators, and stay within one or two lines.

Covers:
- `feat~constraints~1`
