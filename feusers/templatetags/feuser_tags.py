from django import template

register = template.Library()

_AVATAR_COLORS = [
    "#c2478a",
    "#5b6af0",
    "#2ea8a8",
    "#e05c2a",
    "#6a9e2e",
    "#a855b5",
    "#d4902a",
    "#3a8ed4",
    "#e05878",
    "#2e8a5f",
    "#7c6af0",
    "#c47a2a",
]


@register.filter
def avatar_color(initials: str) -> str:
    if not initials:
        return _AVATAR_COLORS[0]
    return _AVATAR_COLORS[hash(initials) % len(_AVATAR_COLORS)]
