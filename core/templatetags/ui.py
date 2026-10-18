"""Small template helpers used across pages."""

import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def query(context, **changes):
    """Current URL's query string with some params changed: {% query d=day view='day' %}.

    Keeps filters (vendor, category...) when moving between periods.
    """
    params = context["request"].GET.copy()
    params.pop("format", None)
    for key, value in changes.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return "?" + params.urlencode()


@register.filter
def as_json(value):
    return mark_safe(json.dumps(value))


@register.filter
def who(user):
    """Display name for whoever entered a row."""
    if not user:
        return "—"
    return user.get_full_name() or user.username
