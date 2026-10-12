"""Text AI Express's description box opens with.

Kept Django-free so it can be unit-tested directly.
"""


def with_typing_space(text: str) -> str:
    """Append one space to a non-empty preset so the user can start typing right away."""
    text = (text or "").rstrip()
    return f"{text} " if text else ""
