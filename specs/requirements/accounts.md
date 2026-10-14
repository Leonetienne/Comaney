# Accounts and Authentication

Sources: `feusers/views/auth.py`, `feusers/views/account.py`, `feusers/rate_limit.py`,
`budget/decorators.py`, `comaney/middleware.py`, docs `admin-manual/registration.md`,
`user-manual/account-settings.md`, `security-audit-tickets/`.

## Registration

### Registration availability
`req~accounts.registration.availability~1`

Where `ENABLE_REGISTRATION` is not `TRUE`, the system shall refuse the registration page with a not-found response and create no account.

Covers:
- `feat~accounts~1`

### Registration fields
`req~accounts.registration.fields~1`

The registration form shall ask for email address, first name, last name, password and password repetition, and shall reject the submission if the passwords differ or the email address is already taken.

Covers:
- `feat~accounts~1`

### Registration proof of work
`req~accounts.registration.proof-of-work~1`

The system shall require every registration submission to carry a nonce solving a single-use, session-bound SHA-256 proof-of-work challenge of 18 bits, and shall reject the submission otherwise.

Rationale:
Deters automated sign-ups on open instances without a third-party captcha.

Covers:
- `feat~accounts~1`

Tags: Security

### Registration with email confirmation
`req~accounts.registration.confirmation~1`

When a registration succeeds while emailing is enabled, the system shall create an unconfirmed account and send a confirmation link to the given address.

Covers:
- `feat~accounts~1`

### Registration confirmation mail failure
`req~accounts.registration.mail-failure~1`

If the confirmation email cannot be sent, then the system shall delete the just-created account and show "We couldn't send a confirmation email to that address."

Covers:
- `feat~accounts~1`

### Registration without email
`req~accounts.registration.no-email~1`

While emailing is disabled, when a registration succeeds, the system shall create the account as confirmed, log the user in and open the dashboard.

Covers:
- `feat~accounts~1`

### Email confirmation
`req~accounts.registration.confirm-link~1`

When a feuser opens a valid confirmation link, the system shall mark the account confirmed and active, invalidate the token, create the user defaults, resolve pending onboarding invitations for that email address, and notify `ADMIN_NOTIFICATION_EMAIL` about the new user if configured.

Covers:
- `feat~accounts~1`

### User defaults
`req~accounts.registration.defaults~1`

When an account is first confirmed, the system shall create the default categories, default tags and default dashboards with their default cards, skipping dashboards and cards if the feuser already has cards.

Comment:
Defaults are declared in `budget/fixtures/` (`DEFAULT_CATEGORIES`, `DEFAULT_TAGS`, `PREDEFINED_DASHBOARD_CARDS`, `DEFAULT_USER_DASHBOARDS`).

Covers:
- `feat~accounts~1`

### Pending invitations on sign-up
`req~accounts.registration.onboarding-invites~1`

When an account is confirmed, the system shall turn every still-valid contact or project onboarding invitation addressed to that email address into the corresponding contact link or project membership.

Covers:
- `feat~accounts~1`

## Login and session

### Login with password
`req~accounts.login.password~1`

When a visitor submits an email address and password matching an active, confirmed account, the system shall either start an authenticated session or, if the account has any second factor, continue with the second-factor challenge.

Covers:
- `feat~accounts~1`

### Login generic failure message
`req~accounts.login.generic-error~1`

If the email address is unknown or the password is wrong, then the system shall answer with the same message "Invalid email or password."

Covers:
- `feat~accounts~1`

Tags: Security

### Login of unconfirmed account
`req~accounts.login.unconfirmed~1`

If the credentials are correct but the account is not confirmed, then the system shall refuse the login with "Please confirm your email address first."

Covers:
- `feat~accounts~1`

### Login rate limit
`req~accounts.login.rate-limit~1`

If 5 failed login attempts occur within 60 seconds for the same client IP or for the same account, then the system shall refuse further attempts from that IP or for that account with "Too many failed attempts. Please wait a moment and try again." until fewer than 5 failures remain in the sliding window.

Rationale:
Keyed per account as well as per IP so distributed guessing against one account is also slowed.

Covers:
- `feat~accounts~1`

Tags: Security

### Rate limit storage
`req~accounts.login.rate-limit-shared~1`

The system shall keep rate-limit counters in the database cache so that all Gunicorn workers share them.

Covers:
- `feat~accounts~1`

Tags: Security

### Session identity
`req~accounts.session.identity~1`

The system shall identify a logged-in feuser solely by `feuser_id` in the server-side session and shall treat a session whose feuser no longer exists or is inactive as logged out.

Covers:
- `feat~accounts~1`

### Protected pages
`req~accounts.session.protected~1`

When a visitor without an authenticated session requests a page requiring login, the system shall redirect to the login page.

Covers:
- `feat~accounts~1`

### Last login and last seen
`req~accounts.session.last-seen~1`

The system shall record the time of each successful login, and shall update a feuser's last-seen time on authenticated requests at most once every 5 minutes.

Covers:
- `feat~accounts~1`

### Logout
`req~accounts.session.logout~1`

When a feuser logs out via POST, the system shall flush the session and show the landing page.

Covers:
- `feat~accounts~1`

### Landing page redirect
`req~accounts.session.landing-redirect~1`

When a logged-in feuser opens the landing page, the system shall redirect to their dashboard.

Covers:
- `feat~accounts~1`

## Password reset

### Password reset request
`req~accounts.password-reset.request~1`

When a visitor requests a password reset for an email address, the system shall send a reset link valid for 1 hour if an active, confirmed account with that address exists, and shall show the same confirmation page whether or not it exists.

Covers:
- `feat~accounts~1`

Tags: Security

### Password reset without email
`req~accounts.password-reset.no-email~1`

While emailing is disabled, the system shall show that password reset is unavailable instead of the reset form.

Covers:
- `feat~accounts~1`

### Password reset completion
`req~accounts.password-reset.complete~1`

When a visitor submits a new password twice on a valid, unexpired reset link, the system shall set the password and invalidate the token; if the token is unknown or expired, then the system shall show an invalid-link page.

Covers:
- `feat~accounts~1`

## Credentials management

### Password change
`req~accounts.password.change~1`

When a feuser submits their current password and a new password twice, the system shall change the password if the current password is correct and the repetitions match.

Covers:
- `feat~accounts~1`

### Email change
`req~accounts.email.change~1`

When a feuser requests an email change with a new, unused address and their current password, the system shall keep the old address active, show the change as pending, and send a confirmation link to the new address.

Covers:
- `feat~accounts~1`

### Email change confirmation
`req~accounts.email.confirm~1`

When the confirmation link of a pending email change is opened, the system shall replace the account email with the pending address.

Covers:
- `feat~accounts~1`

## Account deletion

### Account deletion confirmation
`req~accounts.delete.confirm~1`

When a feuser confirms account deletion with their correct password, the system shall permanently delete the account and all owned data and end the session.

Covers:
- `feat~accounts~1`

### Account deletion keeps contacts' history
`req~accounts.delete.contacts~2`

When an account is deleted, the system shall treat each contact as the keeping side of a contact removal (`req~contacts.kick.history~2`), so the contact's balances and history stay intact.

Covers:
- `feat~accounts~1`

### Account deletion and projects
`req~accounts.delete.projects~1`

When an account is deleted, the system shall delete every project in which it is the only real member, transfer admin rights of other projects it administers to another real member, and replace it by an offline member in the remaining projects.

Covers:
- `feat~accounts~1`

### Account media cleanup
`req~accounts.delete.media~1`

When an account is deleted, the system shall delete its profile picture and backdrop files.

Covers:
- `feat~accounts~1`

Tags: Privacy
