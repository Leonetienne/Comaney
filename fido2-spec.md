# Second-Factor Authentication (TOTP + FIDO2/WebAuthn): Feature Specification

## Overview

Today `FeUser` has a single hardcoded second factor: TOTP (`totp_secret`, `totp_enabled`, `totp_recovery_hash`). This spec generalizes that into a **multi-method second-factor system**: TOTP and FIDO2/WebAuthn ("security keys") are two interchangeable specializations of an abstract `SecondFactorAuth` concept. A user may register several factors of either kind, mark one as primary, and switch methods at login time.

The login area is a security-critical surface and must be built to a high standard: every state transition (primary changed, factor removed mid-session, challenge expired, recovery code used elsewhere) needs a defined, tested outcome, not a happy-path-only implementation. This is explicitly **not** a quick bolt-on; treat it with the same rigor as the settlement/approval logic elsewhere in this codebase.

The architecture must stay clean and registry-driven: a third method (a dedicated YubiKey-specific flow) is planned as a near-term follow-up and must be addable without touching the login view, the removal view, or the templates beyond registering itself.

---

## Data Model

### New: `feusers/models/second_factor.py`

```python
class SecondFactorAuth(models.Model):
    """Shared fields for every 2FA method. Concrete subclasses add their own
    method-specific fields and register themselves in FACTOR_REGISTRY."""
    feuser = models.ForeignKey("feusers.FeUser", on_delete=models.CASCADE, related_name="+")
    label = models.CharField(max_length=64, blank=True)   # user-given device name
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class TOTPFactor(SecondFactorAuth):
    secret = models.CharField(max_length=64)


class WebAuthnFactor(SecondFactorAuth):
    credential_id = models.CharField(max_length=255, unique=True)
    public_key = models.TextField()
    sign_count = models.PositiveIntegerField(default=0)
    transports = models.CharField(max_length=128, blank=True)
```

Django abstract models do not support cross-table queries, so a single-source-of-truth registry replaces scattered `if method == "totp"` branching:

```python
# feusers/second_factor_registry.py
@dataclass
class FactorType:
    key: str                  # "totp" | "webauthn"
    model: type[models.Model]
    display_name: str         # "Authenticator App" | "Security Key"
    setup_view_name: str
    challenge_template: str

FACTOR_REGISTRY: dict[str, FactorType] = {}

def register_factor_type(factor_type: FactorType) -> None:
    FACTOR_REGISTRY[factor_type.key] = factor_type

def get_all_factors(feuser) -> list[SecondFactorAuth]:
    """Single combined, ordered read across every registered factor table.
    Every view that needs 'what methods does this user have' must call this
    once per request and reuse the result for both rendering and validating
    the POST, to avoid a factor being added/removed mid-request."""
    factors = []
    for ft in FACTOR_REGISTRY.values():
        factors.extend(ft.model.objects.filter(feuser=feuser))
    return sorted(factors, key=lambda f: f.created_at)
```

Any future method (YubiKey-specific flow, etc.) adds a model + one `register_factor_type()` call; nothing else changes.

### Modified: `FeUser` model

- Remove `totp_secret`, `totp_enabled`.
- Rename `totp_recovery_hash` -> `twofa_recovery_hash` (now protects *all* factors, not just TOTP).
- Add convenience property `has_2fa_enabled` = `bool(get_all_factors(self))`.

### Migration plan

1. Data migration: for every `FeUser` with `totp_enabled=True`, create a `TOTPFactor(feuser=user, secret=user.totp_secret, is_primary=True, label="Authenticator App")`.
2. Rename `totp_recovery_hash` -> `twofa_recovery_hash` (`RenameField`, preserves existing recovery codes).
3. Drop `totp_secret` / `totp_enabled` from `FeUser`.

---

## Primary-Factor Invariant

Exactly one factor (of any type, across both tables) may have `is_primary=True` per `FeUser` at a time.

```python
# feusers/services/second_factor.py
@transaction.atomic
def set_primary(feuser, factor) -> None:
    for f in get_all_factors(feuser):
        if f.is_primary and (type(f), f.pk) != (type(factor), factor.pk):
            f.is_primary = False
            f.save(update_fields=["is_primary"])
    factor.is_primary = True
    factor.save(update_fields=["is_primary"])
```

Rules:
- The first factor a user ever registers is auto-set as primary.
- Deleting the primary factor while others remain auto-promotes the most-recently-created remaining factor, and shows a one-time notice: "X is now your primary second factor."
- Deleting the last remaining factor also clears `twofa_recovery_hash` (no active 2FA, no recovery code needed; a fresh one is generated the next time the user enables 2FA).

### Setup-flow checkbox

Every "add a factor" flow (`totp_setup`, `webauthn_setup`) shows a checkbox at the final confirmation step: "Use [Authenticator App / Security Key] as primary second factor."

- If this is the user's first factor ever, the checkbox is rendered checked and disabled: it is auto-primary regardless (see rule above), so there is no real choice to offer.
- Otherwise it defaults unchecked. If checked, `set_primary(feuser, new_factor)` runs immediately after the factor row is created, in the same request/transaction as the setup completion, not as a separate follow-up action.
- Copy beneath the checkbox when unchecked and a primary already exists: "Your current primary method stays [existing factor label]." This keeps the consequence visible instead of silently leaving the old primary in place.

---

## Recovery Code (now global, not TOTP-specific)

- Generated once, the moment a user's factor count goes from 0 to 1 (first factor ever, of either type). Shown once, exactly like today's TOTP flow; never retrievable again afterward.
- Adding a 2nd or 3rd factor while one already exists does **not** regenerate it; the existing hash is reused.
- New capability: "Regenerate recovery code" in account settings, gated behind re-verifying a currently active factor. Displays a new code once and invalidates the old one immediately.
- Using the recovery code (`twofa_verify_recovery`, generalized from `totp_verify_recovery`):
  1. Matches against `twofa_recovery_hash`.
  2. Deletes **every** `TOTPFactor` and `WebAuthnFactor` row for the user (the user has just proven they can access none of them, so all are equally suspect).
  3. Clears `twofa_recovery_hash`.
  4. Logs the user in directly, same as today.
- The account-settings copy near any single-factor "Remove" action must say plainly: "Using your recovery code removes ALL of your second-factor methods, not just this one" - so a user trying to drop one key doesn't reach for recovery by mistake and lose the rest.

---

## Removing a Factor

Requirement: removing any one factor needs confirmation via **any other currently active factor** (TOTP can kill WebAuthn and vice versa) - not necessarily the one being removed.

`feusers/views/second_factor.py::factor_remove(request, method_key, factor_id)`:

1. Look up the target factor; 404 if it does not belong to the session user.
2. If the user has exactly one *other* active factor, present that factor's challenge directly.
3. If more than one other active factor exists, show the same method-picker component used at login (see below) scoped to "factors other than the one being removed."
4. If the target is the user's *only* factor, skip re-auth (nothing else to prove); this is equivalent to today's fully-disabling `totp_disable`, and remains reachable through the recovery-code path if the user cannot complete even that.
5. On success: delete the target row; run the primary-factor promotion rule above if needed.

---

## Login Flow

Password step in `login_view` (`feusers/views/auth.py`) is unchanged. What changes is everything after: `if user.totp_enabled` becomes `if user.has_2fa_enabled`, and `totp_pending_id` becomes `twofa_pending_id`. The verification step becomes a single unified, robust view rather than a TOTP-only form.

### UX

1. `twofa_verify` loads `get_all_factors(user)` **once** and keeps that list for the whole request (render + validate), per the anti-desync rule above.
2. The user's primary factor's challenge is shown immediately:
   - TOTP: 6-digit input, as today.
   - WebAuthn: a visible "Use security key" button that calls `navigator.credentials.get()` on click (not silently auto-triggered on page load - some browsers require an explicit user gesture, and silently prompting is surprising UX).
3. A "Try a different method" button/link appears **only if more than one factor exists**, opening a picker listing every other factor by its `label` and method icon. Selecting one re-renders the matching challenge; the newly-chosen method's identity is stored in session (`twofa_active_method`, `twofa_active_factor_id`) and re-validated against the same `get_all_factors` snapshot server-side (never trust the client's choice blindly).
4. "Use a recovery code instead" is always visible regardless of method count.

### Reliability requirements (this is the part that must not be rushed)

- **Shared rate-limit bucket.** All attempts for a given login attempt (TOTP code, WebAuthn assertion failure, recovery code) share one bucket keyed by `twofa_pending_id`, exactly like today's `totp_verify`/`totp_verify_recovery` already share the `"totp"` namespace. Renamed to `"twofa"` and extended to WebAuthn so switching methods can never be used to reset an attacker's attempt budget.
- **Mid-flow factor deletion.** If the challenged factor is removed (e.g. from another tab) between page render and submit, re-validate its existence at submit time. Show "This method is no longer available" and return to the method picker, not a generic "invalid code."
- **Mid-flow total wipeout.** If a recovery code is used in another tab while a `twofa_pending_id` session is active elsewhere, the stale pending session must fail closed: redirect to login with a clear message, never 500 or loop.
- **WebAuthn challenge lifecycle.** The server-generated challenge is single-use and stored server-side (session) with a timestamp; reject verification attempts arriving after a short expiry window (e.g. 2 minutes) to prevent stale-challenge replay.
- **Sign-counter clone detection.** Each successful WebAuthn assertion must report a `sign_count` strictly greater than the stored value, per the FIDO2 spec's clone-detection mechanism. Special-case authenticators that always report `sign_count == 0` (legitimate for some resident-key authenticators) as "unsupported," not a mismatch. A genuine mismatch rejects the login and flags the credential in the account settings UI ("This security key reported an inconsistent state; consider removing and re-registering it") rather than silently disabling it.
- **Session fixation.** Call `request.session.cycle_key()` once the full login (password + second factor) completes, since we are already rewriting this exact code path. Flag as a hardening addition, not currently present in `totp_verify`.
- **Distinct error copy.** WebAuthn ceremonies fail for many different reasons (user cancelled, timeout, no authenticator present, transport mismatch). Each needs its own message; do not collapse them into one generic "invalid code" string the way TOTP currently can, since that would leave users unable to self-diagnose "I don't have my key with me" vs. "something is actually broken."

---

## Templates

- `feusers/templates/feusers/totp_verify.html` is replaced by a generic `twofa_verify.html`: primary-challenge slot (TOTP form or WebAuthn trigger button), collapsible "Try a different method" picker, "Use a recovery code instead" link, per-method error slot, and a loading state for the WebAuthn browser prompt.
- `feusers/templates/feusers/totp_setup.html` is split conceptually into a shared "Two-Factor Authentication" section on the profile page plus two setup flows (`totp_setup.html` mostly unchanged, new `webauthn_setup.html` driving the registration ceremony). Both add the "Use as primary second factor" checkbox described above at their final confirmation step.

## Profile / Account Settings

Replace the single TOTP block with a "Two-Factor Authentication" section:
- List of configured factors: label, method icon, "Primary" pill, created date, "Set as primary" (if not primary), "Remove" (routes through the confirm-with-any-other-factor flow above).
- "Add authenticator app" and "Add security key" buttons.
- "Regenerate recovery code" button.
- Zero-factor empty state offers both methods, as today's single "Enable 2FA" prompt does for TOTP alone.

---

## Demo Users

Per the existing hard rule (2FA setup is on the forbidden list for `is_demo=True`), extend the current `totp_setup` guard (`if feuser.is_demo: return redirect("profile")`) identically to `webauthn_setup`, `factor_remove`, and "Regenerate recovery code." Hide all corresponding buttons in the UI for demo accounts, not just block server-side.

---

## Management Command

`remove_user_2fa` (`feusers/management/commands/remove_user_2fa.py`) is generalized to delete every `TOTPFactor` and `WebAuthnFactor` row for the user and clear `twofa_recovery_hash`, instead of clearing three `FeUser` fields directly. No-op message unchanged if the user already has zero factors.

## REST API

No change. 2FA remains a session/browser login gate only; Bearer-token auth (`api/auth.py`) never inspects factor state, exactly as today.

---

## Dependencies

- `py_webauthn` added to `requirements.txt` (server-side WebAuthn ceremony verification; no account, license, or API key required - see below).
- No change to `pyotp`/`qrcode`.

### Deployment note

WebAuthn requires a secure context (HTTPS, or `localhost` for local dev) and a Relying Party ID that matches the serving domain. Per this app's existing transport model (proxy terminates TLS, app never redirects HTTP->HTTPS), the RP ID must be derived from `SITE_URL` and the feature should degrade gracefully (hide "Add security key") if `SITE_URL` cannot yield a valid RP ID (e.g. bare IP address, which WebAuthn does not support as an RP ID).

---

## Tests

### Unit (`tests/unit/`)

- `test_second_factor_registry.py`: `get_all_factors` returns a stable combined/ordered list across both tables; a newly registered `FactorType` appears automatically without touching call sites.
- `test_second_factor_primary.py`: only one `is_primary=True` at a time across both tables; first-ever factor is auto-primary; deleting the primary auto-promotes the newest remaining factor; deleting the last factor clears `twofa_recovery_hash`; checking "use as primary" during setup of a 2nd/3rd factor demotes the previous primary in the same transaction.
- `test_second_factor_recovery.py`: recovery code generated only on the 0->1 transition; unaffected by adding a 2nd/3rd factor; consuming it deletes all factors of both types and clears the hash.
- `test_webauthn_sign_count.py`: strictly-increasing counter accepted; regression/replay rejected; `sign_count == 0` on both sides treated as "unsupported," not a mismatch.

### E2E (`tests/e2e/auth/`)

- `test_totp.py` (existing): must keep passing unchanged as a regression baseline for the single-TOTP-factor case.
- `test_webauthn.py`: registration and login via Selenium's WebDriver Virtual Authenticator (Chrome DevTools Protocol), covering both a happy-path login and a rejected clone/replay attempt.
- `test_twofa_method_switch.py`: user with both a TOTP factor and a WebAuthn factor can log in with either; "Try a different method" only appears with 2+ factors; switching methods does not reset the shared rate-limit bucket.
- `test_twofa_removal.py`: removing one factor requires confirming a different one; removing the only remaining factor does not require re-auth; primary auto-promotion after removing the primary.
- `test_twofa_recovery_global.py`: recovery code wipes both a TOTP and a WebAuthn factor in one action and logs the user in.
- `test_twofa_demo_blocked.py`: demo users cannot reach setup, removal, or recovery-code regeneration for either method, via both direct view access and UI visibility.

---

## Docs

- Rewrite `docs/src/docs/user-manual/two-factor-auth.md` to cover both methods, the primary-factor concept, method switching at login, and the recovery code now being global rather than TOTP-specific.
- Update `docs/src/docs/admin-manual/console-commands.md` for the generalized `remove_user_2fa`.
- Update `docs/src/docs/dev-manual/architecture.md` to document the `FACTOR_REGISTRY` pattern so a future YubiKey-specific addition follows it.

---

## Open Questions (resolve before implementation)

1. **Scope vs. the planned YubiKey follow-up.** A YubiKey *is* a FIDO2/WebAuthn authenticator already covered by the generic `WebAuthnFactor` flow above. Please clarify what the follow-up adds beyond this spec: vendor-specific attestation checking, a PIN/resident-key-specific UX, or bulk enrollment for e.g. company-issued keys? This affects whether `WebAuthnFactor` needs an `attestation_format` field reserved now to avoid a later migration.
2. **Discoverable credentials / passwordless.** This spec assumes WebAuthn is used strictly as a *second* factor after a password (non-resident credential, no passwordless login). Confirm that's in scope; passwordless login would be a materially larger, separate feature.
3. **RP ID source of truth.** Confirm `SITE_URL` is authoritative for deriving the Relying Party ID in every deployment (self-hosted installs might set `ALLOWED_HOSTS` differently from `SITE_URL`).
