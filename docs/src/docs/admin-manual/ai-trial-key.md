# AI Trial Key

The AI trial key is a shared Anthropic API key that allows users without their own Anthropic account to use Comaney's AI features: [AI Express Creation](../user-manual/ai-express-creation.md), AI-assisted dashboard card creation, and AI tag/category mapping during Catalog Partnership onboarding. All three draw from the same shared key and the same per-user budget.

## Setup

Set these environment variables:

```
AI_PROVIDER=claude
AI_PROVIDER_CLAUDE_API_KEY=sk-ant-...your-key...
AI_TRIAL_USAGE_LIMIT=10
```

`AI_TRIAL_API_KEY` is the deprecated old name of `AI_PROVIDER_CLAUDE_API_KEY` and still works. See [`AI_PROVIDER`](environment-variables.md#ai_provider).

`AI_TRIAL_USAGE_LIMIT` is in US cents. Setting it to `10` gives each user a $0.10/month allowance. Set to `0` for no per-user limit (only your Anthropic account's overall budget applies); Comaney logs a warning at startup in that case, since spending on the shared key is then unlimited.
Please note that the enforced limit is an approximation and no exact limit.

## How it works

- Users who have filled in their own AI settings (see [Account settings](../user-manual/account-settings.md#ai)) always use those and are never limited by Comaney. Everyone else uses the shared key.
- Each user has a `ai_trial_budget_spent` counter on their account (reset to zero monthly by the `reset_trial_budgets` cron job).
- Every AI request on the shared key, from any of the features above, records its API cost (in cents) against the user's counter, also when there is no limit.
- When a user's counter reaches `AI_TRIAL_USAGE_LIMIT`, all AI features are disabled for that user until the next reset. With `AI_TRIAL_USAGE_LIMIT=0` this never happens.
- A per-user budget set with `create_user --ai-trial-budget` or `DEMO_USER_AI_BUDGET` replaces `AI_TRIAL_USAGE_LIMIT` for that account and is always a real cap: `0` there means no shared AI for that account.
- With `AI_PROVIDER=none` (or unset) every AI feature is hidden for everyone; users' saved AI settings are kept.
- If the Anthropic API returns a billing error (account out of credit) or an authentication error (invalid key), on any of the three features, the trial feature is **globally disabled** and a flag file is created. The feature stays disabled until an admin re-enables it.

## The trial flag file

When the trial feature is globally disabled, Comaney creates a flag file at the path specified by `AI_TRIAL_DISABLED_FLAG` (default: `{app_root}/ai_trial_disabled.flag`). The file contains a human-readable reason string.

While this file exists, no user can use the trial key (even if their personal budget is not exhausted). Users with their own Anthropic key are unaffected.

## Admin management page

A superuser can manage the trial key state at `/admin/ai-trial/` (accessible from the Django admin).

The page shows:

- Whether the trial is currently enabled or disabled.
- The reason for disabling (if applicable).
- The per-user monthly limit, "unlimited" for `AI_TRIAL_USAGE_LIMIT=0`, or that no shared key is configured.
- A button to **re-enable** the trial (deletes the flag file).

## Re-enabling after exhaustion

1. Top up your Anthropic account at [console.anthropic.com](https://console.anthropic.com).
2. Log into Comaneys Django backend with a superuser account at `/admin`.
3. Go to `/admin/ai-trial/` and click **Re-enable**.

## Single-user and private instances

For a single-user instance or a private instance where all users have their own Anthropic key, you do not need to configure the trial key at all. Each user provides their own key in Account → Settings → Anthropic API key, and it is used only for their own requests.

## Security note

The trial API key is stored in the environment and used server-side. It is never exposed to the browser. Users cannot retrieve the trial key, only use it indirectly through the Express Creation endpoint.
