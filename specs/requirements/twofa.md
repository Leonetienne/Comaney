# Second-Factor Authentication

Sources: former `fido2-spec.md`, `feusers/second_factor_registry.py`,
`feusers/second_factor_service.py`, `feusers/views/twofa.py`, `feusers/views/webauthn.py`,
`feusers/email_factor_service.py`, `feusers/yubico_otp_service.py`,
docs `user-manual/two-factor-auth.md`.

## Methods

### Supported methods
`req~twofa.methods~1`

The system shall support four second-factor methods: authenticator app (TOTP, 30-second codes), security key (FIDO2/WebAuthn), email code, and YubiKey OTP.

Covers:
- `feat~twofa~1`

### Multiple factors
`req~twofa.multiple~1`

The system shall let a feuser register any number of factors of any method, except at most one email code factor.

Rationale:
A second email factor would always target the same address.

Covers:
- `feat~twofa~1`

### Factor labels
`req~twofa.labels~1`

The system shall store a user-chosen label of at most 64 characters per factor and let the feuser rename it inline from the profile.

Covers:
- `feat~twofa~1`

### Security key availability
`req~twofa.webauthn.availability~1`

Where `SITE_URL` yields no hostname or a bare IP address, the system shall hide security-key setup, since no WebAuthn Relying Party ID can be derived; otherwise the RP ID shall be the hostname of `SITE_URL`.

Covers:
- `feat~twofa~1`

### Email code availability
`req~twofa.email.availability~1`

While emailing is disabled, the system shall hide the email code method everywhere.

Covers:
- `feat~twofa~1`

### YubiKey OTP availability
`req~twofa.yubikey.availability~1`

Where `YUBICO_CLIENT_ID` or `YUBICO_SECRET_KEY` is unset, the system shall hide the YubiKey OTP method everywhere.

Covers:
- `feat~twofa~1`

## Setup

### Add factor menu
`req~twofa.setup.menu~1`

The profile shall offer one "Add new second factor" menu listing every method available on the instance.

Covers:
- `feat~twofa~1`

Tags: UI

### TOTP setup
`req~twofa.setup.totp~1`

When a feuser sets up an authenticator app, the system shall show a QR code for a new secret and activate the factor only after a currently valid code is entered.

Covers:
- `feat~twofa~1`

### Security key setup
`req~twofa.setup.webauthn~1`

When a feuser registers a security key, the system shall run the WebAuthn registration ceremony and store the credential ID, public key, sign counter and transports; if the ceremony fails, then the system shall show "We couldn't register that security key. Please try again."

Covers:
- `feat~twofa~1`

### Email code setup
`req~twofa.setup.email~1`

When a feuser starts email code setup, the system shall send a code to the account address immediately and activate the factor only after that code is entered.

Covers:
- `feat~twofa~1`

### YubiKey OTP setup
`req~twofa.setup.yubikey~1`

When a feuser submits a YubiKey OTP during setup, the system shall validate it against the configured validation server and store the key's 12-character public ID.

Covers:
- `feat~twofa~1`

### YubiKey uniqueness
`req~twofa.setup.yubikey-unique~1`

If the public ID of a submitted YubiKey is already registered on any account, then the system shall refuse it with "This YubiKey is already registered."

Covers:
- `feat~twofa~1`

### Setup conclusion
`req~twofa.setup.finish~1`

When any factor setup completes, the system shall return to the profile's two-factor section, and, if it was the feuser's first factor, show a newly generated recovery code exactly once.

Covers:
- `feat~twofa~1`

## Primary factor

### Exactly one primary
`req~twofa.primary.single~1`

While a feuser has at least one factor, the system shall keep exactly one of their factors, across all methods, marked primary.

Covers:
- `feat~twofa~1`

### First factor is primary
`req~twofa.primary.first~1`

When a feuser registers their first factor, the system shall make it primary.

Covers:
- `feat~twofa~1`

### Primary choice on setup
`req~twofa.primary.on-setup~1`

When a feuser adds a further factor with "use as primary" checked, the system shall make the new factor primary and demote the previous one in the same transaction; unchecked, the previous primary stays.

Covers:
- `feat~twofa~1`

### Set as primary
`req~twofa.primary.set~1`

When a feuser chooses "Set as primary" on a factor, the system shall make it the only primary factor.

Covers:
- `feat~twofa~1`

### Primary promotion on removal
`req~twofa.primary.promote~1`

When the primary factor is removed while other factors remain, the system shall make the most recently created remaining factor primary.

Covers:
- `feat~twofa~1`

## Login challenge

### Challenge after password
`req~twofa.login.challenge~1`

When a feuser with at least one factor passes the password step, the system shall not establish the session but present the primary factor's challenge.

Covers:
- `feat~twofa~1`

Tags: Security

### Security key gesture
`req~twofa.login.webauthn-gesture~1`

The system shall start the WebAuthn assertion only on an explicit user click, never automatically on page load.

Covers:
- `feat~twofa~1`

Tags: UI

### Method switch
`req~twofa.login.switch~1`

While a feuser has more than one factor, the challenge page shall offer "Try a different method" listing the other factors; the server shall validate the chosen factor against the feuser's current factors.

Covers:
- `feat~twofa~1`

### Recovery entry point
`req~twofa.login.recovery-link~1`

The challenge page shall always offer to use the recovery code instead.

Covers:
- `feat~twofa~1`

### Shared attempt budget
`req~twofa.login.rate-limit~1`

If 5 failed second-factor or recovery-code attempts occur within 60 seconds for one pending login, then the system shall refuse further attempts with "Too many failed attempts. Please wait a moment and try again.", regardless of which method is used.

Rationale:
Switching methods must not reset an attacker's attempt budget.

Covers:
- `feat~twofa~1`

Tags: Security

### Factor removed mid-login
`req~twofa.login.factor-gone~1`

If the challenged factor no longer exists when the response is submitted, then the system shall show "This method is no longer available. Please choose another." instead of a generic failure.

Covers:
- `feat~twofa~1`

### WebAuthn challenge lifetime
`req~twofa.login.webauthn-expiry~1`

The system shall keep each WebAuthn challenge single-use in the session and reject any response older than 120 seconds.

Covers:
- `feat~twofa~1`

Tags: Security

### WebAuthn clone detection
`req~twofa.login.sign-count~1`

If a WebAuthn assertion reports a signature counter not greater than the stored one, then the system shall reject it, except when both stored and reported counters are 0.

Covers:
- `feat~twofa~1`

Tags: Security

### Email code validity
`req~twofa.email.code~1`

The system shall derive email codes from a per-factor TOTP secret with a 5-minute step and never store the code itself.

Covers:
- `feat~twofa~1`

Tags: Security

### Email code throttle
`req~twofa.email.throttle~1`

If a feuser requests an email code within 60 seconds of the previous one, or more than 10 within an hour, then the system shall send nothing; the first case shall be shown as "a code was already sent", the second as "Too many code requests. Please try again later."

Covers:
- `feat~twofa~1`

Tags: Security

### Email code throttle purposes
`req~twofa.email.purposes~1`

The system shall throttle email code sends separately for setup, login and confirmation by an authenticated feuser, and clear the login throttle when a correct email code is entered in any of these contexts.

Rationale:
Testing or setting up the method must never block a real login.

Covers:
- `feat~twofa~1`

### Email code target
`req~twofa.email.target~1`

The system shall determine the recipient of an email code solely from server-side session state and never from client-supplied identifiers.

Covers:
- `feat~twofa~1`

Tags: Security

### Email code auto-send
`req~twofa.email.auto-send~1`

When an email code challenge or setup page loads, the system shall send a code automatically and offer a "Resend code" link once the cooldown has passed.

Covers:
- `feat~twofa~1`

Tags: UI

### YubiKey OTP verification
`req~twofa.yubikey.verify~1`

When a YubiKey OTP is submitted, the system shall send a signed request to the configured Yubico validation server (default `https://api.yubico.com`), verify the response signature, and accept the OTP only if the response status is OK and its public ID belongs to the feuser; replays shall be rejected by relying on the server's `REPLAYED_OTP` status.

Covers:
- `feat~twofa~1`

Tags: Security

### Login completion
`req~twofa.login.complete~1`

When a second factor is verified, the system shall establish the authenticated session and record the login time.

Covers:
- `feat~twofa~1`

## Recovery code

### One global recovery code
`req~twofa.recovery.global~1`

The system shall keep one recovery code per feuser, generated only when their factor count goes from 0 to 1, stored only as a hash, and never shown again after the initial display.

Covers:
- `feat~twofa~1`

Tags: Security

### Recovery code use
`req~twofa.recovery.use~1`

When a feuser enters the correct recovery code at login, the system shall delete every factor of every method, clear the recovery code and log the feuser in; a wrong code shall show "Invalid recovery code."

Covers:
- `feat~twofa~1`

### Recovery code regeneration
`req~twofa.recovery.regenerate~1`

When a feuser confirms with one of their active factors and requests a new recovery code, the system shall show a new code once and invalidate the previous one immediately.

Covers:
- `feat~twofa~1`

### Recovery warning
`req~twofa.recovery.warning~1`

The profile shall state that using the recovery code removes all second-factor methods, not just one.

Covers:
- `feat~twofa~1`

Tags: UI

## Management

### Factor list
`req~twofa.manage.list~1`

The profile shall list every factor with label, method, creation date and a primary marker, and offer rename, test, set as primary and remove.

Covers:
- `feat~twofa~1`

### Factor removal confirmation
`req~twofa.manage.remove~1`

When a feuser removes a factor while having other factors, the system shall require confirmation with one of the other factors before deleting it; when it is the only factor, the system shall remove it without re-authentication.

Covers:
- `feat~twofa~1`

### Last factor removal
`req~twofa.manage.remove-last~1`

When a feuser's last factor is removed, the system shall clear the recovery code hash.

Covers:
- `feat~twofa~1`

### Factor test
`req~twofa.manage.test~1`

When a feuser tests a factor, the system shall run that factor's challenge in isolation and report success or failure without changing login or session state.

Rationale:
Lets users tell apart several keys with the same name.

Covers:
- `feat~twofa~1`

### 2FA scope
`req~twofa.scope~1`

The system shall apply second-factor checks to browser logins only; API key authentication shall not inspect factors.

Covers:
- `feat~twofa~1`

### Demo restriction
`req~twofa.demo~1`

If a demo user requests factor setup, factor removal or recovery code regeneration, then the system shall refuse it, and the profile shall hide these actions for demo users.

Covers:
- `feat~twofa~1`

Tags: Demo

### Data export of factors
`req~twofa.export~1`

The account export shall include each factor's method, label, primary flag and creation date, and shall never include secrets, credentials or public IDs needed to authenticate.

Covers:
- `feat~twofa~1`

Tags: Security, Privacy
