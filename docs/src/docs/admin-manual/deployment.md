# Deployment

Comaney is distributed as a Docker image and requires a MariaDB database. A `docker-compose.yml` is the recommended way to run it.

## Minimal docker-compose.yml

```yaml
services:
  web:
    image: leonetienne/comaney:latest
    restart: unless-stopped
    ports:
      - "80:8000"
    depends_on:
      - mariadb
    environment:
      # Generate with:
      # python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
      DJANGO_SECRET_KEY: "change-me-to-a-long-random-string"
      DB_HOST: mariadb
      DB_PORT: 3306
      DB_NAME: comaney
      DB_USER: comaney
      DB_PASSWORD: "change-me"
      SITE_URL: "http://localhost:80"
      ALLOWED_HOSTS: "localhost"
      CSRF_TRUSTED_ORIGINS: "http://localhost"
      # Allow new users to register (disable after initial setup)
      ENABLE_REGISTRATION: "TRUE"
      # No SMTP server? Disable emailing for a quick start.
      # Note: disabling email also disables email verification on registration.
      DISABLE_EMAILING: "TRUE"
      GUNICORN_WORKERS: 1
    volumes:
      - comaney_data:/app/data   # persistent user data (profile pictures, etc.)

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
  comaney_data:
```

## Production docker-compose.yml (with SMTP and HTTPS)

```yaml
services:
  web:
    image: leonetienne/comaney:latest
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"   # bind to localhost; reverse proxy handles TLS
    depends_on:
      - mariadb
    environment:
      DJANGO_SECRET_KEY: "your-secret-key-here"
      DB_HOST: mariadb
      DB_PORT: 3306
      DB_NAME: comaney
      DB_USER: comaney
      DB_PASSWORD: "strong-db-password"
      SITE_URL: "https://budget.example.com"
      ALLOWED_HOSTS: "budget.example.com"
      CSRF_TRUSTED_ORIGINS: "https://budget.example.com"
      ENABLE_REGISTRATION: "FALSE"
      EMAIL_HOST: "smtp.example.com"
      EMAIL_PORT: 587
      EMAIL_USE_TLS: "TRUE"
      EMAIL_HOST_USER: "noreply@example.com"
      EMAIL_HOST_PASSWORD: "smtp-password"
      DEFAULT_FROM_EMAIL: "Comaney <noreply@example.com>"
      ADMIN_NOTIFICATION_EMAIL: "admin@example.com"
      GUNICORN_WORKERS: 2
    volumes:
      - comaney_data:/app/data   # persistent user data (profile pictures, AI trial flag, etc.)

  mariadb:
    image: mariadb:lts
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: comaney
      MARIADB_USER: comaney
      MARIADB_PASSWORD: "strong-db-password"
      MARIADB_ROOT_PASSWORD: "strong-root-password"
    volumes:
      - mariadb_data:/var/lib/mysql

volumes:
  mariadb_data:
  comaney_data:
```

## The /data volume

Comaney stores user-generated files under `/app/data` inside the container. **This directory must be a persistent mounted volume** — if it is missing, the application will refuse to start and display a configuration error page instead.

What is stored there:

| Path | Contents |
|------|----------|
| `/app/data/media/ppics/` | User profile pictures (resized JPEG, one per user) |
| `/app/data/ai_trial_disabled.flag` | AI trial deactivation flag (written by the admin panel) |

Always mount a named volume (or a host path) to `/app/data`. Do not use a `tmpfs` mount, as data would be lost on container restart.

## First run

When the container starts for the first time, the entrypoint runs Django migrations automatically. No manual migration step is needed.

The web service is available on port 8000 inside the container (mapped to 80 or wherever you choose on the host).

## Creating user accounts

With registration enabled (`ENABLE_REGISTRATION=TRUE`) users can sign up through the web UI. You can also create accounts directly from the command line, bypassing the registration flow. Accounts created this way are immediately active and confirmed.

```bash
# Prompted interactively (recommended):
docker exec -it comaney-web-1 python manage.py create_user user@example.com

# Or with password provided directly:
docker exec -it comaney-web-1 python manage.py create_user user@example.com -p "SecurePassword123"
```

To change a user's password later:

```bash
docker exec -it comaney-web-1 python manage.py set_user_password user@example.com
```

## Account recovery

If a user forgets their password or loses access to their TOTP device, you can recover their account from the command line without any downtime.

Reset a forgotten password:

```bash
docker exec -it comaney-web-1 python manage.py set_user_password user@example.com
```

Remove a lost TOTP device so the user can log in with their password again:

```bash
docker exec -it comaney-web-1 python manage.py remove_user_2fa user@example.com
```

See [Console Commands](console-commands.md) for the full reference.

## Creating a superuser

A superuser account is purely optional but required to access the Django admin at `/admin/` and to re-enable the AI trial at `/admin/ai-trial/`. The AI trial deactivates itself if your trial API key runs out of funds.

```bash
docker exec -it <container_name> python manage.py createsuperuser
```

Replace `<container_name>` with the name shown by `docker compose ps` (typically `comaney-web-1`).

## Generating a secret key

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Or with openssl:

```bash
openssl rand -hex 50
```

## Updating

Pull the new image and recreate the container. Migrations run automatically on startup.

```bash
docker compose pull
docker compose up -d
```

## Worker count

The `GUNICORN_WORKERS` variable controls how many Gunicorn worker processes are started. The default is 1. For a small private instance, 1–2 workers is sufficient. Each worker holds a database connection, so set this in proportion to your MariaDB `max_connections`.
