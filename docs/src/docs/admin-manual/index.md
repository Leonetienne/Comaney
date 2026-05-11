# Admin Manual

This manual covers everything needed to deploy and operate a Comaney instance. It assumes familiarity with Docker and basic Linux server administration.

## In this manual

| Section | What it covers |
|---|---|
| [Deployment](deployment.md) | Docker Compose setup, first-run, user and superuser creation |
| [Environment Variables](environment-variables.md) | Complete reference for all configuration variables |
| [Email Configuration](email.md) | SMTP setup, Mailpit for development |
| [Cron Jobs](cron-jobs.md) | Required scheduled tasks and what they do |
| [AI Trial Key](ai-trial-key.md) | Shared Anthropic key management |
| [Registration & Users](registration.md) | Open vs. closed instances, user management |
| [Console Commands](console-commands.md) | All management commands with usage reference |

## Quick-start checklist

1. Copy the minimal `docker-compose.yml` from [Deployment](deployment.md).
2. Generate a `DJANGO_SECRET_KEY` (see [Environment Variables](environment-variables.md)).
3. Set `DB_*` variables to match your MariaDB service.
4. Either configure SMTP (`EMAIL_HOST`, `EMAIL_PORT`) or set `DISABLE_EMAILING=TRUE`.
5. Set `SITE_URL` and `ALLOWED_HOSTS` to your public domain.
6. Set `ENABLE_REGISTRATION=TRUE` for initial setup, then disable it after creating your account.
7. Configure the [cron jobs](cron-jobs.md) on the host.
8. Create a superuser with `docker exec`.
