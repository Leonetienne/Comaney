import hashlib
import secrets

from django.db import models

from api.permissions import KeyAccess, full_access

KEY_PREFIX = "cmy_"
LABEL_MAX_LENGTH = 64


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AgentKey(models.Model):
    """A Bearer key for the MCP server, one per AI client; only its hash is stored."""

    uid = models.BigAutoField(primary_key=True)
    feuser = models.ForeignKey("feusers.FeUser", on_delete=models.CASCADE, related_name="agent_keys")
    label = models.CharField(max_length=LABEL_MAX_LENGTH)
    prefix = models.CharField(max_length=16)
    key_hash = models.CharField(max_length=64, unique=True)
    # {concern: {"read": bool, "write": bool}}
    permissions = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "uid"]

    @classmethod
    def create(cls, feuser, label) -> tuple["AgentKey", str]:
        """New key with full permissions; returns (key, raw secret). The secret is never stored."""
        raw = KEY_PREFIX + secrets.token_urlsafe(32)
        key = cls.objects.create(
            feuser=feuser,
            label=label,
            prefix=raw[:12],
            key_hash=hash_key(raw),
            permissions=full_access(),
        )
        return key, raw

    @property
    def access(self) -> KeyAccess:
        return KeyAccess(self.permissions)
