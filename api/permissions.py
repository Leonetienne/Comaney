"""Key permissions: per concern a read and a write flag, write implies read. Django-free."""
from .registry import CONCERNS, READ, WRITE


def full_permissions(concerns) -> dict:
    return {c: {READ: True, WRITE: True} for c in concerns}


def full_access() -> dict:
    return full_permissions(CONCERNS)


def normalize(perms: dict, concerns) -> dict:
    """One entry per known concern; write implies read, anything missing is off."""
    out = {}
    for concern in concerns:
        entry = perms.get(concern) or {}
        write = bool(entry.get(WRITE))
        out[concern] = {READ: write or bool(entry.get(READ)), WRITE: write}
    return out


def allows(perms: dict, concern: str, access: str) -> bool:
    entry = perms.get(concern) or {}
    if access == WRITE:
        return bool(entry.get(WRITE))
    return bool(entry.get(READ) or entry.get(WRITE))


def from_form(post, concerns) -> dict:
    """Checkbox names read_<concern> / write_<concern> -> normalized permissions."""
    return normalize(
        {c: {READ: post.get(f"read_{c}") == "on", WRITE: post.get(f"write_{c}") == "on"} for c in concerns},
        concerns,
    )


class KeyAccess:
    """A key's stored permissions ({concern: {"read", "write"}}), normalized against the registry's concerns."""

    def __init__(self, stored):
        self.perms = normalize(stored or {}, CONCERNS)

    def allows(self, concern, access) -> bool:
        return allows(self.perms, concern, access)

    def rows(self) -> list:
        """One row per concern for the Restrict panel."""
        return [{"concern": c, "label": label, **self.perms[c]} for c, label in CONCERNS.items()]


def missing(concern, access) -> str:
    return f"{CONCERNS[concern]} {access} permission"
