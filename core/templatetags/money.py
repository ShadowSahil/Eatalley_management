"""Template filters for Indian-style money formatting (₹12,34,567)."""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def indian_group(n):
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def format_inr(value, decimals=0, symbol=True):
    try:
        v = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return value
    neg = v < 0
    v = abs(v).quantize(Decimal(1) if decimals == 0 else Decimal(1).scaleb(-decimals))
    whole, _, frac = f"{v:f}".partition(".")
    out = indian_group(whole) + (f".{frac}" if decimals else "")
    return ("-" if neg else "") + ("₹" if symbol else "") + out


@register.filter
def inr(value, decimals=0):
    """{{ amount|inr }} -> ₹1,23,456   {{ amount|inr:2 }} -> ₹1,23,456.50"""
    return format_inr(value, int(decimals))


@register.filter
def num(value, decimals=0):
    """Indian-grouped number without the rupee sign."""
    return format_inr(value, int(decimals), symbol=False)


@register.filter
def pct(value, total):
    try:
        total = Decimal(total or 0)
        if not total:
            return "–"
        return f"{Decimal(value or 0) * 100 / total:.1f}%"
    except (InvalidOperation, TypeError, ValueError):
        return "–"


@register.filter
def qty(value):
    """Show 2.000 as 2 and 1.250 as 1.25."""
    try:
        v = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    s = f"{v.normalize():f}"
    return s


@register.filter
def sub(value, other):
    try:
        return Decimal(value or 0) - Decimal(other or 0)
    except (InvalidOperation, TypeError, ValueError):
        return value
