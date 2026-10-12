"""Text AI Express's description box opens with.

Kept Django-free so it can be unit-tested directly.
"""

AI_PREPROMPT_MAX_LENGTH = 500


def project_prefill(name: str, preprompt: str = "") -> str:
    """Prompt for creating a project's expenses, followed by its preprompt (if any)."""
    base = f"Create all expenses for project '{name}'"
    preprompt = (preprompt or "").strip()
    return f"{base}. {preprompt}" if preprompt else base


def with_typing_space(text: str) -> str:
    """Append one space to a non-empty preset so the user can start typing right away."""
    text = (text or "").rstrip()
    return f"{text} " if text else ""
