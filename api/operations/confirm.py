"""Signed confirmation tokens for two-step destructive operations (preview, then confirm)."""
import hashlib

from django.core import signing

from ..registry import OpError

MAX_AGE_SECONDS = 600
_SALT = "comaney.api.confirm"


def _caller(ctx):
    return [ctx.feuser.pk, ctx.agent_key.pk if ctx.agent_key else None]


def fingerprint(*parts) -> str:
    return hashlib.sha256(repr(parts).encode()).hexdigest()


def issue(ctx, purpose: str, state: str) -> str:
    """A token valid for 10 minutes, bound to the caller (feuser and agent key), purpose and state."""
    return signing.dumps({"p": purpose, "c": _caller(ctx), "s": state}, salt=_SALT, compress=True)


def check(ctx, token: str, purpose: str, state: str) -> None:
    """Raise OpError unless `token` was issued for this caller, purpose and unchanged state."""
    try:
        data = signing.loads(token, salt=_SALT, max_age=MAX_AGE_SECONDS)
    except signing.SignatureExpired:
        raise OpError("The confirmation token has expired; preview again.")
    except signing.BadSignature:
        raise OpError("Invalid confirmation token.")
    if data.get("p") != purpose or data.get("c") != _caller(ctx):
        raise OpError("The confirmation token belongs to a different request or key.")
    if data.get("s") != state:
        raise OpError("The data changed since the preview; nothing was applied. Preview again.")
