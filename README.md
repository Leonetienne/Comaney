# Comaney 💸
Budgeting that actually fits into your life.  
[Check it out now!](https://comaney.app)

![image](https://raw.githubusercontent.com/Leonetienne/Comaney/refs/heads/master/github-assets/lightdark.png)

> Full documentation is available at `/docs/` on any running instance, or see [`docs/src/`](docs/src/) for the source. Build it with [`docs/build/build-docs.sh`](docs/build/build-docs.sh).

---

## Self-hosting

Comaney runs as a Docker container backed by MariaDB.

### Minimal docker-compose.yml

```yml
services:
  web:
    image: leonetienne/comaney:latest
    restart: unless-stopped
    ports:
      - "80:8000"
    depends_on:
      - mariadb
    environment:
      # Generate: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
      DJANGO_SECRET_KEY: "change-me"
      DB_HOST: mariadb
      DB_PORT: 3306
      DB_NAME: comaney
      DB_USER: comaney
      DB_PASSWORD: "change-me"
      SITE_URL: "http://localhost:80"
      ALLOWED_HOSTS: "localhost"
      CSRF_TRUSTED_ORIGINS: "http://localhost"
      ENABLE_REGISTRATION: "TRUE"   # disable after creating your account
      DISABLE_EMAILING: "TRUE"      # set up SMTP for full functionality
      GUNICORN_WORKERS: 1

  mariadb:
    image: mariadb:lts
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: comaney
      MARIADB_USER: comaney
      MARIADB_PASSWORD: "change-me"
      MARIADB_ROOT_PASSWORD: "change-root-too"
    volumes:
      - mariadb_data:/var/lib/mysql

volumes:
  mariadb_data:
```

### First-run steps

1. `docker compose up -d`
2Register your account at `http://localhost/register/`.
3Set `ENABLE_REGISTRATION: "FALSE"` and restart.

### Required cron jobs

```sh
# Every 5 minutes: notifications, recurring expense generation, auto-settle, end-of-month rollover
*/5 * * * * user docker compose -f /path/to/docker-compose.yml exec -T web python manage.py run_cron

# Monthly: reset AI trial budgets
0 0 1 * * user docker compose -f /path/to/docker-compose.yml exec -T web python manage.py reset_trial_budgets
```

### Key environment variables

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | *(dev placeholder)* | **Required in production.** Signs sessions and CSRF tokens. |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | `127.0.0.1` / `3306` / `comaney` / `comaney` / `comaney` | MariaDB connection. |
| `SITE_URL` | `http://localhost:8080` | Public base URL, embedded in outgoing email links. |
| `ALLOWED_HOSTS` | `*` | Comma-separated list of accepted hostnames. |
| `CSRF_TRUSTED_ORIGINS` | *(empty)* | Required when behind an HTTPS reverse proxy. |
| `ENABLE_REGISTRATION` | `FALSE` | `TRUE` to allow new signups. |
| `DISABLE_EMAILING` | *(unset)* | `TRUE` to suppress all emails (also disables email verification). |
| `EMAIL_HOST` / `EMAIL_PORT` | (none) | SMTP server. Required unless `DISABLE_EMAILING=TRUE`. |
| `EMAIL_USE_TLS` | *(unset)* | `TRUE` for STARTTLS (port 587). |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | *(empty)* | SMTP credentials. |
| `DEFAULT_FROM_EMAIL` | `noreply@comaney.local` | Sender address for outgoing emails. |
| `ADMIN_NOTIFICATION_EMAIL` | *(unset)* | Receives system alerts. Also enables the contact form. |
| `AI_TRIAL_API_KEY` | *(unset)* | Shared Anthropic key for the AI trial feature. |
| `AI_TRIAL_USAGE_LIMIT` | `0` | Per-user monthly cap in US cents. |
| `PUBLIC_PAGE_IMPRINT_MD` | *(unset)* | Path to a Markdown file served at `/impressum/`. |
| `PUBLIC_PAGE_EUDATENSCHUTZ_MD` | *(unset)* | Path to a Markdown file served at `/datenschutzerklaerung/`. |
| `GUNICORN_WORKERS` | `1` | Number of Gunicorn worker processes. |

Full reference: **[Admin Manual → Environment Variables](docs/src/docs/admin-manual/environment-variables.md)**

---

## For developers

### Building front-end assets

```bash
./build/build-assets.sh
```

Runs `npm install && npm run build` inside a `node:25.9.0-slim linux/amd64` container. Never run npm directly on the host; see [Dev Manual: Building Assets](docs/src/docs/dev-manual/building-assets.md).

### Building the documentation

```bash
./docs/build/build-docs.sh
```

Builds the mkdocs site to `docs/build/site/`, then served by Django at `/docs/`.

### Running tests

```bash
# Stack must be running: docker compose up
# Mailpit at :8030, app at :8080
pip install -r requirements-test.txt
cd tests && pytest -vsx
```

See [Dev Manual → Testing](docs/src/docs/dev-manual/testing.md) for full details.

### Building the Docker image

```bash
docker buildx build \
  --platform linux/amd64 \
  -f Deployment/Dockerfile \
  -t leonetienne/comaney:<version> \
  --build-arg APP_VERSION=<version> \
  --push \
  .
```
