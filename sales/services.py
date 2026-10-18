"""Sales numbers for a date range, shared by the Sales dashboard and the P&L."""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Sum

from .models import SaleItemLine, SaleOrder, SalePayment

ZERO = Decimal(0)


def _sum(qs, field):
    return qs.aggregate(v=Sum(field))["v"] or ZERO


def revenue_by_day(start, end):
    """Net revenue (excluding GST) per day.

    Uses the orders report when it exists for a day; otherwise falls back to the
    item-wise report for that day, so a P&L is still possible if only item
    reports were uploaded.
    """
    out = defaultdict(lambda: ZERO)
    order_days = set()
    rows = (
        SaleOrder.objects.filter(date__range=(start, end), is_cancelled=False)
        .values("date")
        .annotate(total=Sum("total"), tax=Sum("tax"))
    )
    for r in rows:
        out[r["date"]] += (r["total"] or ZERO) - (r["tax"] or ZERO)
        order_days.add(r["date"])
    item_rows = (
        SaleItemLine.objects.filter(date__range=(start, end))
        .exclude(date__in=order_days)
        .values("date")
        .annotate(amount=Sum("amount"))
    )
    for r in item_rows:
        out[r["date"]] += r["amount"] or ZERO
    return out


def sales_summary(period):
    start, end = period.start, period.end
    orders = SaleOrder.objects.filter(date__range=(start, end))
    valid = orders.filter(is_cancelled=False)
    items = SaleItemLine.objects.filter(date__range=(start, end))

    n_orders = valid.count()
    gross = _sum(valid, "gross_amount")
    discount = _sum(valid, "discount")
    tax = _sum(valid, "tax")
    total = _sum(valid, "total")
    delivery = _sum(valid, "delivery_charge")
    container = _sum(valid, "container_charge")
    cancelled = orders.filter(is_cancelled=True).aggregate(n=Count("id"), v=Sum("total"))

    def grouped(field):
        rows = (
            valid.values(field)
            .annotate(orders=Count("id"), amount=Sum("total"))
            .order_by("-amount")
        )
        return [
            {"name": r[field] or "Not set", "orders": r["orders"], "amount": r["amount"] or ZERO}
            for r in rows
        ]

    def by_payment():
        # Split (part) payments count towards each mode they were paid with.
        modes = defaultdict(lambda: {"orders": 0, "amount": ZERO})
        paid = (
            SalePayment.objects.filter(order__in=valid)
            .values("mode")
            .annotate(orders=Count("order", distinct=True), amount=Sum("amount"))
        )
        unpaid = (  # orders saved before payment rows existed
            valid.filter(payments__isnull=True)
            .values("payment_mode")
            .annotate(orders=Count("id"), amount=Sum("total"))
        )
        for r in list(paid) + [{"mode": u["payment_mode"], **u} for u in unpaid]:
            m = modes[r["mode"] or "Not set"]
            m["orders"] += r["orders"]
            m["amount"] += r["amount"] or ZERO
        return sorted(({"name": k, **v} for k, v in modes.items()), key=lambda x: x["amount"], reverse=True)

    item_rows = list(
        items.values("item_name", "category")
        .annotate(qty=Sum("quantity"), amount=Sum("amount"))
        .order_by("-amount")
    )
    cat_totals = defaultdict(lambda: {"qty": ZERO, "amount": ZERO})
    for r in item_rows:
        c = cat_totals[r["category"] or "Uncategorised"]
        c["qty"] += r["qty"] or ZERO
        c["amount"] += r["amount"] or ZERO
    categories = sorted(
        ({"name": k, **v} for k, v in cat_totals.items()), key=lambda x: x["amount"], reverse=True
    )

    revenue = revenue_by_day(start, end)
    trend = [ZERO] * len(period.buckets)
    for d, v in revenue.items():
        i = period.bucket_index(d)
        if i is not None:
            trend[i] += v

    discounted = valid.filter(discount__gt=0)

    return {
        "has_orders": orders.exists(),
        "has_items": bool(item_rows),
        "orders": n_orders,
        "gross": gross,
        "discount": discount,
        "discounted_orders": discounted.count(),
        "tax": tax,
        "delivery": delivery,
        "container": container,
        "total": total,
        # Round-off plus bills settled for more/less than the bill (tips, waived change).
        "adjustment": total - (gross - discount + delivery + container + tax),
        "net_revenue": sum(revenue.values(), ZERO),
        "avg_order": (total / n_orders) if n_orders else ZERO,
        "cancelled_count": cancelled["n"] or 0,
        "cancelled_value": cancelled["v"] or ZERO,
        "by_payment": by_payment(),
        "by_order_type": grouped("order_type"),
        "by_source": grouped("source"),
        "items": item_rows,
        "item_qty": sum((r["qty"] or ZERO for r in item_rows), ZERO),
        "item_amount": sum((r["amount"] or ZERO for r in item_rows), ZERO),
        "categories": categories,
        "trend": trend,
        "days_with_sales": len(revenue),
    }
