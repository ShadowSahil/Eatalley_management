from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from core.periods import add_months, month_end

from .models import FixedCost

ZERO = Decimal(0)


def fixed_cost(start, end):
    """Fixed costs for a date range.

    Like salaries, each cost belongs to a month, so a range covering part of a
    month gets that share of it (a daily P&L shows 1/30th of the month's rent).

    Returns {"total", "by_head": [{"name", "amount"}], "months": [...]}; "months"
    works with payroll.services.allocate() for per-day/week buckets.
    """
    per_month = defaultdict(lambda: ZERO)
    by_head = defaultdict(lambda: ZERO)
    rows = (
        FixedCost.objects.filter(month__range=(start.replace(day=1), end))
        .values("month", "head__name")
        .annotate(amount=Sum("amount"))
    )
    shares = {}
    m = start.replace(day=1)
    while m <= end:
        m_end = month_end(m)
        shares[m] = Decimal((min(end, m_end) - max(start, m)).days + 1) / Decimal(m_end.day)
        m = add_months(m, 1)
    for r in rows:
        per_month[r["month"]] += r["amount"]
        by_head[r["head__name"]] += r["amount"] * shares[r["month"]]

    months = [
        {"month": m, "end": month_end(m), "per_day": amount / Decimal(month_end(m).day)}
        for m, amount in per_month.items()
    ]
    total = sum((per_month[m] * shares[m] for m in per_month), ZERO)
    return {
        "total": total.quantize(Decimal("0.01")),
        "by_head": [{"name": n, "amount": a.quantize(Decimal("0.01"))} for n, a in sorted(by_head.items(), key=lambda x: -x[1])],
        "months": months,
    }
