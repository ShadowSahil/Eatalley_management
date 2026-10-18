"""
Reporting periods shared by the Sales, Expenses, Inventory and P&L pages.

A period is picked with two query params:  ?view=<kind>&d=<any date inside it>
(plus ?start=&end= for a custom range). Financial years follow the Indian
April-March calendar, and quarters are financial quarters (Q1 = Apr-Jun).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

VIEW_CHOICES = [
    ("day", "Daily"),
    ("week", "Weekly"),
    ("month", "Monthly"),
    ("quarter", "Quarterly"),
    ("fy", "Financial year"),
    ("custom", "Custom range"),
]
VIEW_KINDS = {k for k, _ in VIEW_CHOICES}


def today():
    return timezone.localdate()


def fy_start_year(d):
    """The calendar year in which d's financial year starts (FY 2026-27 -> 2026)."""
    return d.year if d.month >= 4 else d.year - 1


def fy_label(d):
    y = fy_start_year(d)
    return f"FY {y}-{str(y + 1)[-2:]}"


def add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def month_end(d):
    return add_months(d, 1) - timedelta(days=1)


def parse_date(value, default=None):
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Bucket:
    start: date
    end: date
    label: str


@dataclass
class Period:
    kind: str
    start: date
    end: date
    label: str
    anchor: date
    prev_anchor: date = None
    next_anchor: date = None
    buckets: list = field(default_factory=list)

    @property
    def days(self):
        return (self.end - self.start).days + 1

    @property
    def is_single_day(self):
        return self.start == self.end

    def bucket_index(self, d):
        for i, b in enumerate(self.buckets):
            if b.start <= d <= b.end:
                return i
        return None


def _day_buckets(start, end):
    out, d = [], start
    while d <= end:
        out.append(Bucket(d, d, d.strftime("%d %b")))
        d += timedelta(days=1)
    return out


def _week_buckets(start, end):
    out, d = [], start
    while d <= end:
        e = min(d + timedelta(days=6 - d.weekday()), end)
        out.append(Bucket(d, e, d.strftime("%d %b")))
        d = e + timedelta(days=1)
    return out


def _month_buckets(start, end):
    out, d = [], start
    while d <= end:
        e = min(month_end(d), end)
        out.append(Bucket(d, e, d.strftime("%b %y")))
        d = e + timedelta(days=1)
    return out


def get_period(params, default_kind="month"):
    """Build a Period from request.GET (or any dict-like)."""
    kind = params.get("view") or default_kind
    if kind not in VIEW_KINDS:
        kind = default_kind
    anchor = parse_date(params.get("d"), today())

    if kind == "day":
        start = end = anchor
        label = anchor.strftime("%a, %d %b %Y")
        prev_a, next_a = anchor - timedelta(days=1), anchor + timedelta(days=1)
        buckets = [Bucket(start, end, anchor.strftime("%d %b"))]
    elif kind == "week":
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
        label = f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
        prev_a, next_a = start - timedelta(days=7), start + timedelta(days=7)
        buckets = _day_buckets(start, end)
    elif kind == "month":
        start = anchor.replace(day=1)
        end = month_end(start)
        label = start.strftime("%B %Y")
        prev_a, next_a = add_months(start, -1), add_months(start, 1)
        buckets = _day_buckets(start, end)
    elif kind == "quarter":
        fy = fy_start_year(anchor)
        q = ((anchor.month - 4) % 12) // 3  # 0..3
        start = add_months(date(fy, 4, 1), 3 * q)
        end = add_months(start, 3) - timedelta(days=1)
        label = f"Q{q + 1} {fy_label(anchor)} ({start.strftime('%b')}–{end.strftime('%b %Y')})"
        prev_a, next_a = add_months(start, -3), add_months(start, 3)
        buckets = _week_buckets(start, end)
    elif kind == "fy":
        fy = fy_start_year(anchor)
        start, end = date(fy, 4, 1), date(fy + 1, 3, 31)
        label = fy_label(anchor) + " (Apr–Mar)"
        prev_a, next_a = date(fy - 1, 4, 1), date(fy + 1, 4, 1)
        buckets = _month_buckets(start, end)
    else:  # custom
        start = parse_date(params.get("start"), anchor.replace(day=1))
        end = parse_date(params.get("end"), anchor)
        if end < start:
            start, end = end, start
        anchor = start
        label = f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
        prev_a = next_a = None
        span = (end - start).days
        buckets = (
            _day_buckets(start, end) if span <= 62
            else _week_buckets(start, end) if span <= 190
            else _month_buckets(start, end)
        )

    return Period(kind, start, end, label, anchor, prev_a, next_a, buckets)
