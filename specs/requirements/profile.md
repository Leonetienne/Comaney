# Profile and Personal Settings

Sources: `feusers/views/account.py`, `feusers/forms.py`, `feusers/models/feuser.py`,
`comaney/media_serve.py`, docs `user-manual/account-settings.md`.

### Independent sections
`req~profile.sections~1`

The profile page shall be divided into sections, each saved by its own button without affecting the others.

Covers:
- `feat~profile~1`

Tags: UI

## Profile picture

### Profile picture upload
`req~profile.picture.upload~1`

When a feuser uploads a JPEG, PNG, GIF or WebP image of at most 5 MB as profile picture, the system shall let them crop it, then store it as a 256x256 JPEG; if the file is too large or not a valid image, then the system shall reject it with an error message.

Covers:
- `feat~profile~1`

### Initials fallback
`req~profile.picture.initials~1`

While a feuser has no profile picture, the system shall show their initials (first letters of first and last name, or the first two letters of the email address).

Covers:
- `feat~profile~1`

### Profile picture removal
`req~profile.picture.remove~1`

When a feuser removes their profile picture, the system shall delete the file and show initials again.

Covers:
- `feat~profile~1`

## Backdrop

### Backdrop upload
`req~profile.backdrop.upload~1`

When a feuser uploads a PNG, JPEG, WebP or GIF of at most 20 MB as backdrop, the system shall store it and display it fixed behind the main content area of every page for that feuser only.

Covers:
- `feat~profile~1`

### Backdrop privacy
`req~profile.backdrop.private~1`

The system shall serve a backdrop image only to its owner.

Covers:
- `feat~profile~1`

Tags: Privacy, Security

### Backdrop settings
`req~profile.backdrop.settings~1`

The system shall let a feuser set backdrop mode (cover or fit), opacity (0 to 100) and two free CSS declaration boxes of up to 2000 characters, one for all screens and one for screens up to 768 px, previewed live while typing.

Covers:
- `feat~profile~1`

### Backdrop CSS sanitising
`req~profile.backdrop.css-sanitise~1`

The system shall strip the characters `< > { } & @` backtick and backslash from backdrop CSS before storing it.

Rationale:
Prevents breaking out of the style context.

Covers:
- `feat~profile~1`

Tags: Security

## Personal info

### Personal fields
`req~profile.info.fields~1`

The system shall let a feuser edit first name, last name (each up to 128 characters) and currency symbol (up to 10 characters, default €).

Covers:
- `feat~profile~1`

### Currency is cosmetic
`req~profile.info.currency~1`

The system shall use the currency symbol for display only and never convert amounts.

Covers:
- `feat~profile~1`

### Financial month settings
`req~profile.info.month-start~1`

The system shall let a feuser set the financial month start day (1 to 31) and whether it lies in the previous calendar month, and shall show a preview of the resulting month ranges before saving.

Covers:
- `feat~profile~1`

### Unspent allowance action
`req~profile.info.allowance-action~1`

The system shall let a feuser choose what happens to unspent budget at the end of a financial month: dropped (default) or deposited as savings.

Covers:
- `feat~profile~1`

### Unspent allowance deposit
`req~profile.allowance.transition~1`

When a new financial month has started for a feuser whose action is "deposit as savings" and the previous financial month's income minus expenses minus net savings (own, active expenses) is positive, the system shall create one settled savings deposit "Unspent allowance (YYYY-MM)" for that amount dated at the previous month's last day, at most once per financial month.

Covers:
- `feat~profile~1`

## Preferences

### Notification preferences
`req~profile.prefs.notifications~1`

The system shall offer a master email notification switch plus one switch per notification class (see [notifications.md](notifications.md)), all on by default.

Covers:
- `feat~profile~1`

### Expense entry preference
`req~profile.prefs.unclassified-warning~1`

The system shall offer an "Expense entry" setting that turns the missing category/tags save warning back on; demo users cannot change it.

Covers:
- `feat~profile~1`

### Early access
`req~profile.prefs.early-access~1`

The system shall offer "Enable early access features", off by default, which unlocks Sankey Studio and any future early access feature.

Covers:
- `feat~profile~1`

### AI settings section
`req~profile.prefs.ai~1`

The system shall offer an AI section with the active provider's own-settings fields, custom instructions of up to 4096 characters, and a switch to hide all AI UI for this feuser.

Comment:
Details in [ai.md](ai.md).

Covers:
- `feat~profile~1`

## API key

### API key generation
`req~profile.api-key.generate~2`

When a feuser without an API key generates one, the system shall create a new random key and show it with a copy button.

Covers:
- `feat~profile~1`

### API key revocation
`req~profile.api-key.revoke~1`

When a feuser revokes their API key, the system shall delete it so it no longer authenticates.

Covers:
- `feat~profile~1`

### API key demo restriction
`req~profile.api-key.demo~1`

If a demo user requests an API key, then the system shall refuse it.

Covers:
- `feat~profile~1`

Tags: Demo

### Identity demo restriction
`req~profile.demo-identity~1`

If a demo user tries to change their name, email address or password, or delete the account, then the system shall refuse it and the profile shall show these controls disabled.

Covers:
- `feat~profile~1`

Tags: Demo
