from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from core.periods import add_months, month_end, today

from .models import SalaryPayment, Staff

ZERO = Decimal(0)


def salary_cost(start, end, as_of=None, estimate_from=None):
    """Salary cost for a date range.

    Salaries are monthly, so a range that covers part of a month gets that
    share of the month (a daily P&L shows 1/30th of the month's salary).

    For each person and month:
      * once a "salary" payment is recorded, the month is settled and the cost
        is everything paid for it (salary + advances + bonus);
      * until then the month (if it has started) is estimated at their monthly
        salary, so the P&L isn't flattered by salaries not yet paid. Advances
        already paid count as the actual part of that estimate. In the current
        month only the days worked so far are estimated (18 Oct = 18/31).

    Months before `estimate_from` (when the business started using the app)
    are never estimated.

    Returns {"total", "actual", "estimated", "months": [...]}.
    """
    as_of = as_of or today()
    paid = defaultdict(lambda: ZERO)  # (staff_id, month) -> amount
    settled = set()
    rows = (
        SalaryPayment.objects.filter(month__range=(start.replace(day=1), end))
        .values("staff_id", "month", "kind")
        .annotate(amount=Sum("amount"))
    )
    for r in rows:
        paid[(r["staff_id"], r["month"])] += r["amount"]
        if r["kind"] == "salary":
            settled.add((r["staff_id"], r["month"]))

    staff = list(Staff.objects.all())
    by_id = {s.id: s for s in staff}
    months, actual_total, est_total = [], ZERO, ZERO
    m = start.replace(day=1)
    while m <= end:
        m_end = month_end(m)
        overlap = (min(end, m_end) - max(start, m)).days + 1
        share = Decimal(overlap) / Decimal(m_end.day)
        can_estimate = m <= as_of and (estimate_from is None or m >= estimate_from.replace(day=1))
        actual = estimate = ZERO
        worked = Decimal(min(as_of, m_end).day) / Decimal(m_end.day) if m <= as_of else ZERO
        staff_ids = {sid for (sid, mm) in paid if mm == m}
        staff_ids |= {s.id for s in staff if s.employed_during(m, m_end)} if can_estimate else set()
        for sid in staff_ids:
            got = paid.get((sid, m), ZERO)
            actual += got
            if can_estimate and (sid, m) not in settled and sid in by_id and by_id[sid].employed_during(m, m_end):
                estimate += max(by_id[sid].monthly_salary * worked - got, ZERO)
        months.append({
            "month": m,
            "end": m_end,
            "actual": actual,
            "estimated": estimate,
            "share": share,
            "per_day": (actual + estimate) / Decimal(m_end.day),
        })
        actual_total += actual * share
        est_total += estimate * share
        m = add_months(m, 1)

    return {
        "total": (actual_total + est_total).quantize(Decimal("0.01")),
        "actual": actual_total.quantize(Decimal("0.01")),
        "estimated": est_total.quantize(Decimal("0.01")),
        "months": months,
    }


def allocate(months, start, end):
    """Salary cost between two dates, using the per-day rate of each month."""
    total = ZERO
    for m in months:
        lo, hi = max(start, m["month"]), min(end, m["end"])
        if lo <= hi:
            total += m["per_day"] * ((hi - lo).days + 1)
    return total
