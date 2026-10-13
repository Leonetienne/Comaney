"""Agent key permissions: per concern a read and a write flag, write implies read. Django-free."""

READ = "read"
WRITE = "write"


def full_permissions(concerns) -> dict:
    return {c: {READ: True, WRITE: True} for c in concerns}


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
