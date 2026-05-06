import hashlib
import secrets

from django.utils import timezone

from .models import FeUser


_POW_DIFFICULTY = 18


def _new_pow_challenge(request) -> str:
    challenge = secrets.token_hex(16)
    request.session["pow_challenge"] = challenge
    return challenge


def _check_pow(challenge: str, nonce_str: str) -> bool:
    try:
        nonce = int(nonce_str)
        if nonce < 0:
            return False
    except (ValueError, TypeError):
        return False
    digest = hashlib.sha256(f"{challenge}:{nonce}".encode()).digest()
    bits = _POW_DIFFICULTY
    for byte in digest:
        if bits <= 0:
            break
        if bits >= 8:
            if byte != 0:
                return False
            bits -= 8
        else:
            if byte >> (8 - bits) != 0:
                return False
            break
    return True


def _get_session_feuser(request):
    feuser_id = request.session.get("feuser_id")
    if not feuser_id:
        return None
    try:
        return FeUser.objects.get(pk=feuser_id, is_active=True)
    except FeUser.DoesNotExist:
        return None


def _record_login(user: FeUser) -> None:
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
