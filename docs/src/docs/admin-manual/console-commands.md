# Console Commands

All management commands are run inside the container via `docker exec`:

```bash
docker exec -it comaney-web-1 python manage.py <command> [args]
```

Replace `comaney-web-1` with the name shown by `docker compose ps` if yours differs.

---

## User management

### create_user

Creates a confirmed, active user account without going through the registration flow.

```
python manage.py create_user <email> [-p <password>]
```

If `-p` is omitted, the password is prompted interactively (with confirmation). The account is immediately usable: no email confirmation step is required.

```bash
# Interactive (recommended on shared terminals):
docker exec -it comaney-web-1 python manage.py create_user alice@example.com

# Non-interactive:
docker exec -it comaney-web-1 python manage.py create_user alice@example.com -p "SecurePass1"
```

Exits with an error if the email is already in use or the password is empty.

---

### set_user_password

Updates the password for an existing account.

```
python manage.py set_user_password <email> [-p <password>]
```

If `-p` is omitted, the new password is prompted interactively (with confirmation).

```bash
docker exec -it comaney-web-1 python manage.py set_user_password alice@example.com
```

Exits with an error if no account with that email exists.

---

### remove_user_2fa

Disables two-factor authentication for a user. Use this when a user is locked out after losing their TOTP device and recovery code.

```
python manage.py remove_user_2fa <email>
```

Clears the TOTP secret, recovery hash, and enabled flag. The user can then log in with their password and re-enable 2FA from their profile. The command is idempotent: running it when 2FA is already off prints a notice and exits cleanly.

```bash
docker exec -it comaney-web-1 python manage.py remove_user_2fa alice@example.com
```

Exits with an error if no account with that email exists.

---

### delete_user

Permanently deletes a user account and all associated data (expenses, categories, tags, recurring expenses, dashboard cards).

```
python manage.py delete_user <email> [--yes]
```

Without `--yes`, the command asks for confirmation before proceeding. Type `yes` to confirm; anything else aborts. This operation is irreversible.

```bash
# Interactive:
docker exec -it comaney-web-1 python manage.py delete_user alice@example.com

# Skip confirmation (for scripts):
docker exec -it comaney-web-1 python manage.py delete_user alice@example.com --yes
```

Exits with an error if no account with that email exists.

---

## Cron commands

These are intended to run on a schedule. See [Cron Jobs](cron-jobs.md) for the recommended cron entries.

### run_cron

Runs all scheduled maintenance tasks in sequence: scheduled expense generation, auto-settle, allowance transitions, and expense notifications.

```
python manage.py run_cron [--year YEAR --month MONTH]
```

The optional `--year` and `--month` flags override the current financial month for all users, which is useful for testing or manual backfills.

---

### reset_trial_budgets

Resets the AI trial usage counter for every user. Run once per month.

```
python manage.py reset_trial_budgets
```
