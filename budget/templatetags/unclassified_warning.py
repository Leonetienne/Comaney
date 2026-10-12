"""
Missing category/tags warning before saving an expense.

Usage in templates (once per page, before the page's own scripts):
    {% load unclassified_warning %}
    {% unclassified_save_warning_js request.feuser %}

Then register each form with
    window.addUnclassifiedSaveWarning(form, getItems)
"""
from django import template

from ..unclassified import save_warning_config

register = template.Library()


@register.inclusion_tag("budget/partials/_unclassified_save_warning_js.html")
def unclassified_save_warning_js(feuser):
    return {"config": save_warning_config(feuser)}
