# Developer Manual

This manual covers the architecture, build pipeline, and development workflow for contributors and anyone extending Comaney.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web framework | Django 5 |
| WSGI server | Gunicorn |
| Database | MariaDB via `mysqlclient` |
| Static files | WhiteNoise (served from Gunicorn, no separate web server needed) |
| Frontend | Alpine.js v3, Chart.js, CodeMirror 6 |
| CSS | SCSS compiled to CSS |
| JS bundling | esbuild |
| Container | Docker (linux/amd64) |

## Python dependencies

All runtime dependencies are in `requirements.txt`:

| Package | Purpose |
|---|---|
| `Django` | Web framework |
| `gunicorn` | Production WSGI server |
| `mysqlclient` | MariaDB driver |
| `whitenoise` | Static file serving |
| `PyYAML` | Dashboard card YAML parsing |
| `anthropic` | AI express creation |
| `Pillow` | Receipt image processing |
| `pyotp` + `qrcode` | TOTP two-factor authentication |
| `Markdown` | Dynamic public page rendering |

## Dev setup

The development stack runs entirely in Docker. You do not need Python or MariaDB installed locally.

**Prerequisites:** Docker with Compose.

```bash
# Clone the repo
git clone ...
cd Comaney

# Create a .env file (see Admin Manual for env vars; for dev most defaults work)
# The docker-compose.yml already sets sensible dev defaults.

# Start the stack (database, mailpit, and the web app)
docker compose up

# App: http://localhost:8080
# Mailpit (outgoing email capture): http://localhost:8030
```

On first start, Django runs `migrate` automatically. To create a superuser:

```bash
docker exec -it comaney-web-1 python manage.py createsuperuser
```

**Building frontend assets** (CSS and JS) is a separate step. See [Building Assets](building-assets.md). You need to build the frontend assets to have a working development instance.

## Key conventions

- **Never use `request.user` or `@login_required`.** Comaney has its own user model (`FeUser`) and session auth. Use `@feuser_required` instead, which sets `request.feuser`.
- **Always create expenses via `create_expense()`** in `budget/expense_factory.py`, not `Expense()` directly. The factory handles M2M tags and post-save setup.
- **CSS custom properties only** for theme colours. Do not replace them with SCSS `$variables`: CSS custom properties are needed for dynamic light/dark switching at runtime.
- **Tests are mandatory** for all functional features. See [Testing](testing.md).
