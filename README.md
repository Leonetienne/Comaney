# [[EXPERIMENTAL / IN-DEV]]
# Comaney
A no-BS, zero-effort budgetting software as a self-hostable django web application.  
Readme to be done.


## Dev zone
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

```
pip install -r requirements-test.txt

# Run the full suite
pytest tests/ -vsx

# Run a single topic file
pytest tests/test_30_expenses.py -vsx

# Run a single test by name
pytest tests/ -vsx -k test_70_standard_month_start_day_1
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
