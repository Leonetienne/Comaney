# AI Trial Key

The AI trial key is a shared Anthropic API key that allows users without their own Anthropic account to use the [AI Express Creation](../user-manual/ai-express-creation.md) feature.

## Setup

Set two environment variables:

```
AI_TRIAL_API_KEY=sk-ant-...your-key...
AI_TRIAL_USAGE_LIMIT=10
```

`AI_TRIAL_USAGE_LIMIT` is in US cents. Setting it to `10` gives each user a $0.10/month allowance. Set to `0` for no per-user limit (only your Anthropic account's overall budget applies).
Please note that the enforced limit is an approximation and no exact limit.

## How it works

- Each user has a `ai_trial_budget_spent` counter on their account (reset to zero monthly by the `reset_trial_budgets` cron job).
- Every Express Creation request records the API cost (in cents) against the user's counter.
- When a user's counter reaches `AI_TRIAL_USAGE_LIMIT`, the Express Creation feature is disabled for that user until the next reset.
- If the Anthropic API returns a billing error (account out of credit) or an authentication error (invalid key), the trial feature is **globally disabled** and a flag file is created. The feature stays disabled until an admin re-enables it.

## The trial flag file

When the trial feature is globally disabled, Comaney creates a flag file at the path specified by `AI_TRIAL_DISABLED_FLAG` (default: `{app_root}/ai_trial_disabled.flag`). The file contains a human-readable reason string.

While this file exists, no user can use the trial key (even if their personal budget is not exhausted). Users with their own Anthropic key are unaffected.

## Admin management page

A superuser can manage the trial key state at `/admin/ai-trial/` (accessible from the Django admin).

The page shows:

- Whether the trial is currently enabled or disabled.
- The reason for disabling (if applicable).
- A button to **re-enable** the trial (deletes the flag file).

## Re-enabling after exhaustion

1. Top up your Anthropic account at [console.anthropic.com](https://console.anthropic.com).
2. Log into Comaneys Django backend with a superuser account at `/admin`.
3. Go to `/admin/ai-trial/` and click **Re-enable**.

## Single-user and private instances

For a single-user instance or a private instance where all users have their own Anthropic key, you do not need to configure the trial key at all. Each user provides their own key in Account → Settings → Anthropic API key, and it is used only for their own requests.

## Security note

The trial API key is stored in the environment and used server-side. It is never exposed to the browser. Users cannot retrieve the trial key, only use it indirectly through the Express Creation endpoint.
