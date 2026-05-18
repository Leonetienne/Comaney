import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

AVATAR_COLORS = [
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
        return AVATAR_COLORS[0]
    return AVATAR_COLORS[hash(initials) % len(AVATAR_COLORS)]


@register.simple_tag
def avatar_colors_json() -> str:
    return mark_safe(json.dumps(AVATAR_COLORS))
