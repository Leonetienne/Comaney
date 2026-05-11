# Registration & Users

## Open vs. closed instances

Comaney supports two modes of operation controlled by `ENABLE_REGISTRATION`:

### Closed (private) instance: `ENABLE_REGISTRATION=FALSE`

The registration page returns a 403. No new accounts can be created. Use this for personal or family instances after your accounts are set up.

**Typical setup flow:**
1. Start with `ENABLE_REGISTRATION=TRUE`.
2. Register your account(s).
3. Set `ENABLE_REGISTRATION=FALSE` and restart the container.

### Open (public) instance: `ENABLE_REGISTRATION=TRUE`

Anyone who can reach the site can create an account. Account creation uses a proof-of-work challenge to mitigate bot spam (the browser must compute a SHA-256 hash before the form can be submitted).

When email is enabled, new users must confirm their email address before they can log in. When `DISABLE_EMAILING=TRUE`, users are auto-confirmed and can log in immediately.

## User management

Comaney has no built-in admin UI for managing user accounts beyond the Django admin. Use the Django admin at `/admin/` (requires superuser) to:

- View and edit user records.
- Deactivate accounts (`is_active = False`).
- Inspect or clear TOTP settings.

## Superuser creation

A superuser is a special account that can log into the Django admin:

```bash
docker exec -it comaney-web-1 python manage.py createsuperuser
```

## The contact form

The contact form at `/contact/` is only available when **both** of these are true:

- `ENABLE_REGISTRATION=TRUE`
- `ADMIN_NOTIFICATION_EMAIL` is set

This is intentional: the contact form is for users and potential users who want to reach the admin, which only makes sense on a public instance. On a closed private instance, both conditions are typically false and
there are other means to contact an admin.

## EU/DE legal pages

For public instances hosted in Germany (or subject to GDPR), you are required to display an Impressum and a Datenschutzerklärung. Comaney supports this via markdown files:

```
PUBLIC_PAGE_IMPRINT_MD=/app/legal/impressum.md
PUBLIC_PAGE_EUDATENSCHUTZ_MD=/app/legal/datenschutz.md
```

When set, these pages appear in the footer and are publicly accessible without login. Mount the markdown files into the container via a volume.

```yaml
volumes:
  - ./legal:/app/legal:ro
```
