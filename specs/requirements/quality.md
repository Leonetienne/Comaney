# Quality Requirements

Sources: AGENTS.md (Rules, Transport / TLS), `comaney/settings.py`,
`comaney/json_utils.py`, docs `admin-manual/deployment.md`, `dev-manual/testing.md`.

## Security

### Server-side authorisation
`req~quality.security.authz~1`

The system shall check ownership or membership on the server for every read and write of user data, independent of what the UI shows.

Covers:
- `feat~quality~1`

Tags: Security

### Shared expense authorisation
`req~quality.security.buddy-authz~1`

If a request names an upfront payer or participant who is neither the feuser's contact nor offline contact, nor a member of the selected project, then the system shall reject it.

Covers:
- `feat~quality~1`

Tags: Security

### Escaped embedded data
`req~quality.security.json-embed~1`

The system shall escape `<`, `>` and `&` in all JSON embedded in HTML script blocks.

Rationale:
Names and titles written by other users must not break out of a script element.

Covers:
- `feat~quality~1`

Tags: Security

### CSRF
`req~quality.security.csrf~1`

The system shall require a valid CSRF token for every state-changing browser request.

Covers:
- `feat~quality~1`

Tags: Security

### Password storage
`req~quality.security.passwords~1`

The system shall store passwords only as salted hashes, recovery codes only as hashes, and generate all tokens and API keys with a cryptographically secure generator.

Covers:
- `feat~quality~1`

Tags: Security

### Uploaded images
`req~quality.security.images~1`

The system shall verify and re-encode every uploaded image before storing it.

Covers:
- `feat~quality~1`

Tags: Security

### Robust parameters
`req~quality.security.params~1`

If a request carries a malformed or out-of-range parameter (year, month, date, ID, JSON body), then the system shall answer with a client error or fall back to a default, never a server error.

Covers:
- `feat~quality~1`

Tags: Security

## Transport

### No in-app HTTPS enforcement
`req~quality.transport.no-redirect~1`

The system shall speak plain HTTP behind a TLS-terminating proxy and shall not redirect to HTTPS, emit HSTS or inspect `X-Forwarded-Proto`.

Rationale:
App-side redirects behind a TLS-terminating proxy cause redirect loops; redirect and HSTS belong to the proxy.

Covers:
- `feat~quality~1`

Tags: Security, Operations

### Secure cookies
`req~quality.transport.cookies~1`

While `DEBUG` is off, the system shall mark session and CSRF cookies `Secure`.

Covers:
- `feat~quality~1`

Tags: Security

## Self-containment and privacy

### No runtime downloads
`req~quality.selfcontained.assets~1`

The system shall serve all fonts, images, scripts and libraries locally and load nothing from the internet at runtime, except calls to the configured AI provider and the Yubico OTP validation server.

Covers:
- `feat~quality~1`

Tags: Privacy

### Static asset caching
`req~quality.selfcontained.static~1`

The system shall serve static files with content-hashed names, compressed, for long-term browser caching.

Covers:
- `feat~quality~1`

Tags: Performance

### Data sent to AI
`req~quality.privacy.ai~1`

The system shall send to the AI provider only what a feature needs (catalog names, relevant expense metadata, the user's input) and never the feuser's transaction history in bulk.

Covers:
- `feat~quality~1`

Tags: Privacy

### Privacy of classification
`req~quality.privacy.overlay~1`

The system shall never show a participant's personal category, tags or note on a foreign expense to anyone else.

Covers:
- `feat~quality~1`

Tags: Privacy

## Reliability and performance

### Transactional changes
`req~quality.reliability.atomic~1`

Multi-step changes (merges, settlements, account deletion, partnership apply, bulk saves) shall be atomic: either all of their effects persist or none.

Covers:
- `feat~quality~1`

### Cheap per-page work
`req~quality.performance.badges~1`

Navigation badges computed on every page shall use count-only queries.

Covers:
- `feat~quality~1`

Tags: Performance

### Low-traffic target
`req~quality.performance.scale~1`

The system shall be dimensioned for small self-hosted instances; a single Gunicorn worker shall be sufficient for a household.

Covers:
- `feat~quality~1`

Tags: Performance

## Maintainability

### Tests for changes
`req~quality.maint.tests~1`

Every new feature and every fix shall come with automated tests: pure logic as unit tests without Django, user-visible behaviour as Selenium end-to-end tests verified through the UI.

Covers:
- `feat~quality~1`

### Full e2e run
`req~quality.maint.no-skips~1`

A full end-to-end run in the development environment shall skip no test; only genuinely absent environment features may skip.

Covers:
- `feat~quality~1`

### Documentation in sync
`req~quality.maint.docs~1`

A feature change shall update the user, admin or developer manual, `AGENTS.md` and this requirements database in the same change.

Covers:
- `feat~quality~1`

### Plain-language user docs
`req~quality.maint.docs-audience~1`

The user manual shall be written for non-technical users.

Covers:
- `feat~quality~1`
