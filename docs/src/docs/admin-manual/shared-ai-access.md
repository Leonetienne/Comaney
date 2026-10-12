# Shared AI Access

Shared AI access is the AI access you configure for the whole instance. It lets users without AI settings of their own use Comaney's AI features: [AI Express Creation](../user-manual/ai-express-creation.md), AI-assisted dashboard card creation, AI tag/category mapping during Catalog Partnership onboarding, and Unclassified Expenses. All of them draw from the same shared access and the same per-user budget.

## Setup

Pick a service with [`AI_PROVIDER`](environment-variables.md#ai_provider) and configure its shared access as described for that service on [AI Providers](ai-providers.md) (usually a shared API key, `AI_PROVIDER_<NAME>_API_KEY`). Then set the per-user limit:

```
AI_TRIAL_USAGE_LIMIT=10
```

`AI_TRIAL_USAGE_LIMIT` is in US cents. Setting it to `10` gives each user a $0.10/month allowance. Set to `0` for no per-user limit (only the AI service's own account budget applies); Comaney logs a warning at startup in that case, since spending on the shared access is then unlimited.
The enforced limit is an approximation, not an exact cap.

`AI_TRIAL_API_KEY` is the deprecated old name of `AI_PROVIDER_CLAUDE_API_KEY` and still works with `AI_PROVIDER=claude`.

## How it works

- Users who have filled in their own AI settings (see [Account settings](../user-manual/account-settings.md#ai)) always use those and are never limited by Comaney. Everyone else uses the shared access.
- Each user has a `ai_trial_budget_spent` counter on their account (reset to zero monthly by the `reset_trial_budgets` cron job).
- Every AI request on the shared access, from any of the features above, records its cost (in cents) against the user's counter, also when there is no limit. What a request costs is computed by the service's provider (see "Cost" on [AI Providers](ai-providers.md)).
- When a user's counter reaches `AI_TRIAL_USAGE_LIMIT`, all AI features are disabled for that user until the next reset. With `AI_TRIAL_USAGE_LIMIT=0` this never happens.
- A per-user budget set with `create_user --ai-trial-budget` or `DEMO_USER_AI_BUDGET` replaces `AI_TRIAL_USAGE_LIMIT` for that account and is always a real cap: `0` there means no shared AI for that account.
- With `AI_PROVIDER=none` (or unset) every AI feature is hidden for everyone; users' saved AI settings are kept.
- If the AI service returns a billing error (account out of credit) or rejects the shared key, on any of the features, shared access is **globally disabled**, a flag file is created and the address in `ADMIN_NOTIFICATION_EMAIL` gets an email. Shared access stays disabled until an admin re-enables it.

## The flag file

When shared access is globally disabled, Comaney creates a flag file at the path specified by `AI_TRIAL_DISABLED_FLAG` (default: `{app_root}/ai_trial_disabled.flag`). The file contains a human-readable reason string.

While this file exists, no user can use the shared access (even if their personal budget is not exhausted). Users with their own AI settings are unaffected.

## Admin management page

A superuser can manage shared access at `/admin/ai-trial/` (accessible from the Django admin).

The page shows:

- Whether shared access is currently enabled or disabled.
- The reason for disabling (if applicable).
- The per-user monthly limit, "unlimited" for `AI_TRIAL_USAGE_LIMIT=0`, or that shared access is off.
- A button to **re-enable** shared access (deletes the flag file).

## Re-enabling after exhaustion

1. Fix the cause: top up the account with your AI service (the admin page links its billing page if the service has one), or set a valid shared key and restart the container.
2. Log into Comaney's Django backend with a superuser account at `/admin`.
3. Go to `/admin/ai-trial/` and click **Re-enable shared access**.

## Single-user and private instances

For a single-user instance or a private instance where all users have their own key, you do not need shared access at all. Each user enters their own key under Account → Settings → AI, and it is used only for their own requests. Whether a service offers own keys is listed on [AI Providers](ai-providers.md).

## Security note

The shared key is stored in the environment and used server-side. It is never exposed to the browser. Users cannot retrieve it, only use it indirectly through the AI features.
