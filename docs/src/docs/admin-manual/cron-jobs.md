# Cron Jobs

Comaney requires two management commands to run on a schedule inside the web container. Without them, recurring expenses are not generated, due-date notifications are not sent, auto-settle does not fire, and end-of-month rollover does not happen.

## Required cron jobs

### `run_cron`: every 5 minutes

```cron
*/5 * * * * <user> docker compose -f /path/to/docker-compose.yml exec -T web python manage.py run_cron
```

**What it does:**

1. **Materialises recurring expenses.** For each active `ScheduledExpense`, computes upcoming instances (based on the recurrence rule) and creates `Expense` records for them if they don't already exist.

2. **Sends due-date notifications.** Scans all unsettled expenses with `notify=True` and sends email alerts when an expense is in the `soon` (2–4 days away), `tomorrow`, `today`, or `late` (overdue) class, but only if it hasn't already sent that class for this expense.

3. **Auto-settles expenses.** For expenses with `auto_settle_on_due_date=True`, marks them settled when their due date passes.

4. **Processes end-of-month rollover.** When a user's financial month transitions, checks whether unspent budget should be deposited to savings or carried over, and creates the appropriate `Expense` record.

5. **Resets the demo user (if enabled).** When `ENABLE_DEMO_USERS=TRUE`, checks whether the demo account's `last_seen` is older than one week. If so, deletes the account and recreates it with a clean slate. See [Demo user](environment-variables.md#demo-user) for configuration.

### `reset_trial_budgets`: monthly (1st of each month)

```cron
0 0 1 * * <user> docker compose -f /path/to/docker-compose.yml exec -T web python manage.py reset_trial_budgets
```

**What it does:** Resets `ai_trial_budget_spent` to zero for every user. This allows each user a fresh allowance of the shared Anthropic trial key in the new calendar month.

## Setting up cron on the host

The cron jobs run on the **host machine** via `docker exec` (or `docker compose exec`), not inside the container's own cron daemon. This is intentional; container restart and lifecycle management stays with Docker, not with cron inside the container.

### Example `/etc/cron.d/comaney`

```cron
*/5 * * * * comaney docker compose -f /home/comaney/comaney/docker-compose.yml exec -T web python manage.py run_cron >> /var/log/comaney-cron.log 2>&1

0 0 1 * * comaney docker compose -f /home/comaney/comaney/docker-compose.yml exec -T web python manage.py reset_trial_budgets >> /var/log/comaney-cron.log 2>&1
```

Replace `comaney` with the system user that owns the docker-compose file, and adjust the path accordingly.

### Notes

- The `-T` flag disables pseudo-TTY allocation, which is required when running `docker compose exec` from cron (no interactive terminal).
- If you use `docker exec` instead of `docker compose exec`, replace the command with:
  ```
  docker exec -T comaney-web-1 python manage.py run_cron
  ```
  where `comaney-web-1` is the container name shown by `docker ps`.
- Redirect output (`>> logfile 2>&1`) to avoid cron sending emails for every invocation.

## What happens if cron is not running

| Feature | Effect without cron |
|---|---|
| Recurring expenses | Not generated; recurring transactions never appear |
| Due-date notifications | Never sent |
| Auto-settle | Never fires; expenses stay unsettled indefinitely |
| End-of-month rollover | Never happens; no carry-over or savings deposit is created |
| AI trial budget reset | Never resets; users stay at their monthly cap permanently |
| Demo user reset | Never fires; demo account accumulates data indefinitely |

Comaney will otherwise continue to function normally; you can still create, edit, and view expenses manually.
