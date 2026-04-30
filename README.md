# [[EXPERIMENTAL / IN-DEV]]
# Comaney
A no-BS, zero-effort budgetting software as a self-hostable django web application.  
Readme to be done.


## For admins
If the trial anthropic api key runs out of budget, the trial feature will disable itself.  
It must be manually re-enabled at `/admin/ai-trial/` using a superuser.  
Create a superuser with `python manage.py createsuperuser`, potentially executed in the container.

## Environment variables
| Variable | Default | Description                                                                                                                                       |
|---|---|---------------------------------------------------------------------------------------------------------------------------------------------------|
| `DJANGO_SECRET_KEY` | — | Django secret key. Generate one with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DB_HOST` | `db` | MySQL host                                                                                                                                        |
| `DB_PORT` | `3306` | MySQL port                                                                                                                                        |
| `DB_NAME` | `comaney` | MySQL database name                                                                                                                               |
| `DB_USER` | `comoney` | MySQL user                                                                                                                                        |
| `DB_PASSWORD` | `comaney` | MySQL password                                                                                                                                    |
| `SITE_URL` | `http://localhost:8080` | Public base URL of the instance; used in outgoing emails and links                                                                                |
| `DEBUG` | `FALSE` | Set to `TRUE` to enable Django debug mode                                                                                                         |
| `ENABLE_REGISTRATION` | `FALSE` | Set to `TRUE` to allow new users to register. Disable on closed/private instances after setting up your account.                                  |
| `DISABLE_EMAILING` | *(unset)* | Set to `TRUE` to suppress all outgoing emails and to disable email verification. Useful when no SMTP server is available.                         |
| `EMAIL_HOST` | — | SMTP hostname                                                                                                                                     |
| `EMAIL_PORT` | `25` | SMTP port                                                                                                                                         |
| `AI_TRIAL_API_KEY` | *(unset)* | Anthropic API key used for the limited AI trial feature available to users without their own key                                                  |
| `AI_TRIAL_USAGE_LIMIT` | `5` | Per-user, per-month spending cap for the trial key, in US cents                                                                                   |
| `PUBLIC_PAGE_IMPRINT_MD` | *(unset)* | Path to a Markdown file. If set, a legal imprint page is added to the footer.                                                                     |
| `PUBLIC_PAGE_EUDATENSCHUTZ_MD` | *(unset)* | Path to a Markdown file. If set, a Datenschutzerklärung page is added to the footer.                                                              |
| `ADMIN_NOTIFICATION_EMAIL` | *(unset)* | Email address that receives system notifications                                                                                                  |


## For devs
### Building docker file
```
docker buildx build \
  --platform linux/amd64 \
  -f Deployment/Dockerfile \
  -t leonetienne/comaney:0.1.0<change version!!> \
  --push \
  .
```

### Building SCSS
```
npm install
npm run build:css      # one-off compile → static/dist/main.css
npm run watch:css      # recompile on every save
```
Source files live in `build/scss/`. The compiled output at `static/dist/main.css` is what Django serves.

### Running tests

The test suite is split into files by topic and runs in numeric prefix order.
The app must be running at `http://localhost:8080` and mailpit at `http://localhost:8030`.
Cron tests require the web container to be reachable via `docker exec comoney-web-1`.
Running individual test files or individual tests is untested and will probably not work
as some are dependent on each other :(. A PR to make tests self-reliant would be a banger.

```
pip install -r requirements-test.txt

# Run the full suite
pytest tests/ -vsx

```

Test files:
| File | Coverage |
|---|---|
| `test_10_auth.py` | Registration, email confirmation, login |
| `test_20_categories_tags.py` | Category and tag CRUD, inline rename |
| `test_30_expenses.py` | Expense CRUD, all field types, list view, dashboard, CSV export |
| `test_40_scheduled.py` | Scheduled expense CRUD, all fields |
| `test_50_profile.py` | Profile update, API key generate/verify |
| `test_55_expenses_advanced.py` | All expense field types, dashboard totals, list view, CSV export |
| `test_56_scheduled_advanced.py` | All scheduled expense fields, list view |
| `test_60_api.py` | Full REST API CRUD (account, categories, tags, expenses, scheduled) |
| `test_70_cron.py` | Financial month boundaries, scheduled generation, duplicates, auto-settle |
| `test_80_totp.py` | TOTP 2FA setup, login, disable |
| `test_90_teardown.py` | API key revoke, account export ZIP, cleanup, account deletion |
