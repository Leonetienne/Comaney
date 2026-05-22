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

### Creating a user account

Use the `create_user` management command to create a regular user account without going through the registration flow. The account is immediately active and confirmed.

```bash
# Password provided directly:
docker exec -it comaney-web-1 python manage.py create_user user@example.com -p "SecurePassword123"

# Password prompted interactively (safer for shared terminals):
docker exec -it comaney-web-1 python manage.py create_user user@example.com
```

### Changing a user's password

Use `set_user_password` to update the password for an existing account:

```bash
# Password provided directly:
docker exec -it comaney-web-1 python manage.py set_user_password user@example.com -p "NewPassword456"

# Password prompted interactively:
docker exec -it comaney-web-1 python manage.py set_user_password user@example.com
```

### Removing two-factor authentication

If a user is locked out because they have lost their TOTP device and recovery code, you can disable 2FA for their account:

```bash
docker exec -it comaney-web-1 python manage.py remove_user_2fa user@example.com
```

After this, the user can log in with their password alone and re-enable 2FA from their profile.

### Deleting a user account

To permanently delete a user and all their data:

```bash
# Interactive confirmation:
docker exec -it comaney-web-1 python manage.py delete_user user@example.com

# Skip confirmation prompt:
docker exec -it comaney-web-1 python manage.py delete_user user@example.com --yes
```

This deletes the account and all associated expenses, categories, tags, recurring expenses, and dashboard cards. The operation is irreversible.

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
