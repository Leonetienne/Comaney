# Email Configuration

Comaney uses email for:

- Account registration confirmation
- Email address change confirmation
- Password reset links
- Expense due-date notifications
- Settlement notifications
- Admin alerts (new registrations, AI trial key events, contact form submissions)

## Requirements

You must either configure a valid SMTP connection **or** explicitly set `DISABLE_EMAILING=TRUE`. If neither is done, Comaney starts but shows a system-misconfigured banner on every page and email features do not work.

## SMTP configuration

```
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=TRUE
EMAIL_HOST_USER=noreply@example.com
EMAIL_HOST_PASSWORD=your-smtp-password
DEFAULT_FROM_EMAIL=Comaney <noreply@example.com>
```

### Port and TLS guide

| Port | Protocol | `EMAIL_USE_TLS` |
|---|---|---|
| 25 | Unencrypted SMTP | `FALSE` or unset |
| 465 | Implicit TLS (SMTPS) | Not directly supported; use a relay |
| 587 | STARTTLS (recommended) | `TRUE` |
| 1025 | Mailpit / local relay | `FALSE` or unset |

## Development: Mailpit

[Mailpit](https://mailpit.axllent.org/) is a lightweight local email server that captures all outgoing emails without delivering them. It exposes a web UI to browse captured messages.

```yaml
services:
  web:
    environment:
      EMAIL_HOST: mailpit
      EMAIL_PORT: 1025

  mailpit:
    image: axllent/mailpit
    ports:
      - "8030:8025"   # web UI
```

Browse captured emails at `http://localhost:8030`.

## Disabling email (quick-start mode)

```
DISABLE_EMAILING=TRUE
```

When email is disabled:

- New accounts are auto-confirmed. Users can log in immediately after registration without clicking a confirmation link.
- Password reset does not work (no email can be sent).
- Expense notifications are not sent.
- Admin alerts are not sent.

This is fine for a private single-user instance where you trust all users, but unsuitable for a public instance with self-registration.

## Troubleshooting

**"System misconfigured" banner after startup:**
You have neither set valid SMTP variables nor `DISABLE_EMAILING=TRUE`. Set one or the other.

**Registration confirmation email not arriving:**
Check `SITE_URL`; if it points to the wrong host, the confirmation link in the email goes nowhere.

**CSRF error after clicking email link:**
Set `CSRF_TRUSTED_ORIGINS` to match your public URL.
