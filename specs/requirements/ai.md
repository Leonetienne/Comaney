# AI

Sources: `budget/ai_service.py`, `budget/ai_availability.py`, `budget/ai_trial.py`,
`ai_providers/`, `feusers/ai_user_config.py`, `budget/express_service.py`,
`budget/views/express.py`, `budget/unclassified_ai.py`, former `ai-providers-plan.md`,
docs `admin-manual/ai-providers.md`, `shared-ai-access.md`, `user-manual/ai-express-creation.md`.

## Provider selection

### Provider setting
`req~ai.provider.select~1`

The system shall use the AI provider named by `AI_PROVIDER`: a file name in `ai_providers/` (built in: `claude`, `deepseek`, `local`, or a mounted community file), or `none`.

Covers:
- `feat~ai~1`

### AI off
`req~ai.provider.off~1`

While `AI_PROVIDER` is `none` or unset, the system shall hide every AI entry point for everyone and keep users' saved AI settings.

Covers:
- `feat~ai~1`

### Misconfiguration
`req~ai.provider.misconfigured~1`

If `AI_PROVIDER` is unknown, the provider file cannot be loaded, its settings fail validation, or `AI_PROVIDER` is unset while `AI_TRIAL_API_KEY` or any `AI_PROVIDER_*` variable is set, then the system shall show a configuration error page naming the variable to fix instead of running.

Rationale:
AI is never switched off silently by an upgrade or typo.

Covers:
- `feat~ai~1`

Tags: Operations

### Provider settings scope
`req~ai.provider.scope~1`

The system shall pass each provider only the environment variables with its own `AI_PROVIDER_<NAME>_` prefix, prefix stripped and keys lower-cased.

Covers:
- `feat~ai~1`

### Deprecated key name
`req~ai.provider.legacy-key~1`

Where `AI_PROVIDER=claude` and `AI_TRIAL_API_KEY` is set, the system shall use it as `AI_PROVIDER_CLAUDE_API_KEY` and log a deprecation warning; if both are set to different values, then the system shall show the configuration error page.

Covers:
- `feat~ai~1`

### Claude provider
`req~ai.provider.claude~1`

The `claude` provider shall call Anthropic's API with the configured model (default `claude-sonnet-5-5`), answer token cap (default 8192) and effort (`low` to `max`, default `medium`), cache cacheable system prompt parts, bill each attempt at its own model's price, and refuse to start with an unknown model unless both price overrides are set.

Covers:
- `feat~ai~1`

### DeepSeek provider
`req~ai.provider.deepseek~1`

The `deepseek` provider shall call `https://api.deepseek.com` with Bearer authentication, bill cached and uncached input separately at peak prices, and support images only for vision-capable models.

Covers:
- `feat~ai~1`

### Self-hosted provider
`req~ai.provider.local~1`

The `local` provider shall call any OpenAI-compatible server at the required base URL and model, send `Authorization: Bearer` only when a key is set, support images only when `SUPPORTS_VISION` is true, bill `CENTS_PER_MTOK` per million tokens, wait up to `TIMEOUT` seconds (default 600), and offer shared access only when `SHARED_ACCESS` is true (default).

Covers:
- `feat~ai~1`

### Missing usage
`req~ai.provider.no-usage~1`

If an OpenAI-compatible server reports no token usage, then the system shall bill the call at 0 and log this once per process.

Covers:
- `feat~ai~1`

### Error mapping
`req~ai.provider.errors~1`

Providers shall map vendor failures to typed errors: authentication (401/403), billing (402 or billing-worded 429), transient (other 429, 5xx, timeouts, connection errors), refusal, invalid response and vision unsupported.

Covers:
- `feat~ai~1`

## Access and budgets

### Own settings win
`req~ai.access.own~1`

When a feuser's own AI settings for the active provider are complete, the system shall use them and never limit that feuser's AI use.

Covers:
- `feat~ai~1`

### Shared access
`req~ai.access.shared~1`

While a feuser has no complete own settings and the provider offers shared access, the system shall use the instance's shared access, limited per feuser per calendar month by `AI_TRIAL_USAGE_LIMIT` in US cents, where 0 means no limit.

Covers:
- `feat~ai~1`

### Per-user budget override
`req~ai.access.special-budget~1`

Where a feuser has an individual AI budget (set by `create_user --ai-trial-budget`, or a non-zero `DEMO_USER_AI_BUDGET` for demo accounts), the system shall use it instead of the global limit, with 0 meaning no shared AI for that feuser.

Covers:
- `feat~ai~1`

### Usage recording
`req~ai.access.record~1`

The system shall add the cost of every AI call on shared access, successful or failed after repair, to the feuser's monthly spend, also when no limit applies.

Covers:
- `feat~ai~1`

### Budget reached
`req~ai.access.budget-reached~1`

While a feuser's shared-access spend has reached their limit, the system shall refuse their AI requests before contacting the provider, keep AI entry points visible, and explain on the AI Express page that the monthly budget is used up.

Covers:
- `feat~ai~1`

### Monthly reset
`req~ai.access.reset~1`

When `reset_trial_budgets` runs, the system shall reset every feuser's shared-access spend to zero.

Covers:
- `feat~ai~1`

### Shared access failure
`req~ai.access.shared-failure~1`

If the provider rejects the shared credentials or reports a billing failure on shared access, then the system shall disable shared access globally by writing the flag file with a reason, email `ADMIN_NOTIFICATION_EMAIL` with the provider's details, show users a "server is misconfigured" message, and hide AI entry points from users without own settings.

Covers:
- `feat~ai~1`

Tags: Operations

### Re-enable shared access
`req~ai.access.reenable~1`

The admin page `/admin/ai-trial/` shall show whether shared access is enabled, the disable reason, the per-user limit ("unlimited" for no limit) and a button to re-enable it by deleting the flag file; it shall be reachable by superusers only.

Covers:
- `feat~ai~1`

Tags: Operations

### Unlimited warning
`req~ai.access.unlimited-warning~1`

Where shared access has no per-user limit, the system shall log a warning at startup.

Covers:
- `feat~ai~1`

Tags: Operations

### Hide AI per user
`req~ai.access.hide-ui~1`

While a feuser has "disable AI UI" on, the system shall hide every AI entry point for them.

Covers:
- `feat~ai~1`

## Own AI settings

### Generated form
`req~ai.settings.form~1`

The profile shall render one field per user field declared by the active provider, show secret fields masked as `********` plus the last 4 characters, keep the stored secret when the masked value is resubmitted, and clear a field submitted empty.

Covers:
- `feat~ai~1`

### Settings validation
`req~ai.settings.validate~1`

If submitted own settings fail the provider's field or cross-field validation, then the system shall show the error on the field or the form and save nothing.

Covers:
- `feat~ai~1`

### Active provider entry only
`req~ai.settings.scope~1`

The system shall store own settings per provider, use only the active provider's entry, and write only that entry on save.

Covers:
- `feat~ai~1`

### Purge inactive provider settings
`req~ai.settings.purge~1`

While a provider is active, the system shall delete users' settings of other providers at container start and on every cron run; while no provider is active it shall delete nothing.

Covers:
- `feat~ai~1`

Tags: Privacy

### Demo restriction
`req~ai.settings.demo~1`

If a demo user tries to change their own AI settings, then the system shall refuse it and show the fields disabled.

Covers:
- `feat~ai~1`

Tags: Demo

### Custom instructions
`req~ai.settings.instructions~1`

The system shall include the feuser's custom instructions in every AI Express, unclassified and tag suggestion request.

Covers:
- `feat~ai~1`

## Response handling

### JSON repair
`req~ai.response.repair~1`

If an AI answer that must be JSON does not parse, then the system shall make exactly one repair call through the same provider and, unless `AI_NOTIFY_ADMIN_JSON_REPAIR=FALSE`, email the admin which feature was affected and whether the repair succeeded, without user data.

Covers:
- `feat~ai~1`

### Result envelope
`req~ai.response.envelope~1`

For features with a failure case, the system shall expect `{"result": "good", ...}` or `{"result": "fail", "msg": ...}` and show the `msg` of a fail result to the user.

Covers:
- `feat~ai~1`

### Payload validation
`req~ai.response.validate~1`

The system shall validate every AI payload before using it and silently drop references to entries outside the catalog sent with the request.

Covers:
- `feat~ai~1`

Tags: Security

### Provider-neutral wording
`req~ai.wording~1`

User-facing AI text shall not name a vendor except in the provider-specific settings and admin pages, and shall make no claim about where the model runs.

Covers:
- `feat~ai~1`

## Images

### Vision gating
`req~ai.vision.gate~1`

Where the provider does not support images, the system shall hide every image input of AI features, and if an image still reaches the server, then the system shall answer "The configured AI cannot read images." without calling the AI.

Covers:
- `feat~ai~1`

### Image preprocessing
`req~ai.vision.preprocess~1`

The system shall accept JPEG, PNG, GIF and WebP uploads for AI Express, downscale them to at most 1600 px on the longer side and re-encode them as JPEG before sending.

Covers:
- `feat~ai~1`

## AI Express

### Entry points
`req~ai.express.entry~1`

Where AI is available, the system shall offer AI Express from "Add Expense" and from the add button on the expense list and project pages.

Covers:
- `feat~ai~1`

### Input
`req~ai.express.input~1`

AI Express shall accept a free-text description and, where vision is available, a receipt image via upload, drag and drop or paste.

Covers:
- `feat~ai~1`

### Prefill
`req~ai.express.prefill~1`

When AI Express is opened with a `prefill` parameter, the system shall put that text plus one trailing space into the description and place the cursor at its end.

Covers:
- `feat~ai~1`

### Suggested items
`req~ai.express.items~1`

When the AI answers, the system shall show the suggested expenses as editable cards (title, type, value, payee, date, category, tags, assignment) and save only the items the feuser confirms.

Covers:
- `feat~ai~1`

### Grouping
`req~ai.express.grouping~1`

The AI Express prompt shall instruct the AI to combine receipt items with the same category and tags into one expense.

Covers:
- `feat~ai~1`

### Catalog by index
`req~ai.express.catalog~1`

The system shall send the AI only the feuser's categories, tags, non-archived projects (name, description, preprompt, member names) and direct buddy names, referencing people by position index, and never existing transactions.

Covers:
- `feat~ai~1`

Tags: Privacy

### Assignment suggestions
`req~ai.express.assignment~1`

The system shall let the AI assign an item to a project (with included participants, pinned shares and upfront payer) or to one direct buddy (with payer and share), mutually exclusive, defaulting to the feuser as payer and equal shares.

Covers:
- `feat~ai~1`

### Share normalisation
`req~ai.express.shares~1`

If the AI's pinned shares exceed 100 percent, or all included participants are pinned with a sum other than 100, then the system shall rescale them proportionally to 100; a single remaining participant shall get 100.

Covers:
- `feat~ai~1`

### Project preprompt
`req~ai.express.preprompt~1`

The system shall apply a project's AI preprompt only to items assigned to that project, overridable by the feuser's description.

Covers:
- `feat~ai~1`

### Prompt blocks
`req~ai.express.blocks~1`

The system shall omit the direct-buddy prompt block when the feuser has no direct buddies, all project blocks when they have no non-archived project, and the participant and payer blocks when no project has more than one member.

Rationale:
Saves tokens.

Covers:
- `feat~ai~1`

### Success link
`req~ai.express.success~1`

After saving, the success message's "View expenses" link shall lead to the Buddy Expenses page if all items are direct buddy expenses, the project page if all belong to one project, and the expense list otherwise.

Covers:
- `feat~ai~1`

## Tag suggestion

### AI select tags
`req~ai.tags.suggest~1`

When a feuser clicks "AI: select tags" on the expense or recurring expense form, the system shall send the form's current, possibly unsaved values and replace the tag selection with the suggestion, chosen only from the feuser's own tags, and show the call's cost; the category is context only and stays unchanged.

Covers:
- `feat~ai~1`
