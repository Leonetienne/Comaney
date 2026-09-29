# TICKET-05 — TOTP recovery-code verification has no rate limiting

**Severity:** Medium (brute-force of the 2FA recovery code / account takeover second factor)
**Type:** Authentication hardening
**Components:** `feusers/views/totp.py` (`totp_verify_recovery`, `totp_disable` recovery branch)

## Summary

`totp_verify` (the normal 6-digit OTP step during login) is rate limited via
`is_limited("totp", ...)` / `record_failure`. Its sibling `totp_verify_recovery`,
which accepts the account's recovery code to bypass 2FA and log in, has **no** rate
limiting at all. The recovery branch of `totp_disable` is likewise unthrottled.

An attacker who already has the victim's password (the recovery step is only reached
after `totp_pending_id` is set, i.e. password already verified) can submit recovery
codes as fast as they like.

## Root cause

`feusers/views/totp.py`, `totp_verify_recovery`:

```python
def totp_verify_recovery(request):
    pending_id = request.session.get("totp_pending_id")
    ...
    if request.method == "POST":
        user = FeUser.objects.get(pk=pending_id, is_active=True, totp_enabled=True)
        recovery = request.POST.get("recovery", "").strip().upper().replace("-", "")
        digest = hashlib.sha256(recovery.encode()).hexdigest()
        if user.totp_recovery_hash and secrets.compare_digest(digest, user.totp_recovery_hash):
            ...  # logs in and disables 2FA
        error = "Invalid recovery code."       # no record_failure(), no is_limited()
```

The recovery code is `secrets.token_hex(5)` → 40 bits of entropy, which is strong, so
online brute force is impractical *today*. But the asymmetry is a latent gap: the
control that protects the OTP path is simply absent on the recovery path, and if the
code format is ever shortened/changed the exposure becomes real. Comparison uses
`secrets.compare_digest` (good — constant time), so timing is not the issue; request
volume is.

## Proposed fix

Apply the same limiter used by `totp_verify`, keyed on the pending user id:

```python
rl_key = str(pending_id)
if is_limited("totp", rl_key):
    error = "Too many failed attempts. Please wait a moment and try again."
else:
    ... verify ...
    if match:
        rl_clear("totp", rl_key)
        ...
    else:
        record_failure("totp", rl_key)
        error = "Invalid recovery code."
```

Do the same in the recovery branch of `totp_disable` (keyed on the logged-in
`feuser.pk`). Share the `"totp"` bucket so OTP and recovery attempts count together.
(This ticket composes with TICKET-04 — once the limiter is shared/persistent, this
path inherits that too.)

## Regression testing

- **Unit/integration**: drive `totp_verify_recovery` with N+1 wrong recovery codes and
  assert the (N+1)th is rejected with the throttle message, not evaluated.
- Assert a correct recovery code still succeeds and calls `rl_clear`.
- Assert the `totp_disable` recovery branch is throttled the same way.
- Confirm OTP and recovery attempts share one counter (5 bad OTP + 1 recovery trips).
