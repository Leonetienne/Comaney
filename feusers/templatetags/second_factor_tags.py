from django import template
from django.templatetags.static import static as static_url

from ..second_factor_registry import factor_type_for

register = template.Library()


@register.simple_tag
def factor_icon(method_key: str) -> str:
    return static_url(factor_type_for(method_key).icon)


@register.simple_tag
def factor_display_name(method_key: str) -> str:
    return factor_type_for(method_key).display_name
