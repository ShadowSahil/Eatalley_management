"""Profit & loss: sales in, daily expenses + inventory bills + fixed costs + salaries out."""

from decimal import Decimal

from django.db.models import Sum

from core.periods import today
from expenses.models import DailyExpense, ExpenseCategory
from fixedcosts.services import fixed_cost
from inventory.models import InventoryCategory, Purchase
from payroll.models import SalaryPayment
from payroll.services import allocate, salary_cost
from sales.models import SaleItemLine, SaleOrder
from sales.services import revenue_by_day

ZERO = Decimal(0)
# Daily-expense categories that are food/drink ingredients, counted with
# inventory towards "food cost %".
FOOD_EXPENSE_CATEGORIES = {"dairy", "beverages", "veg_fruit", "grocery"}


def tracking_start():
    """First date anything was recorded — salaries aren't estimated before this."""
    firsts = [
        SaleOrder.objects.order_by("date").values_list("date", flat=True).first(),
        SaleItemLine.objects.order_by("date").values_list("date", flat=True).first(),
        DailyExpense.objects.order_by("date").values_list("date", flat=True).first(),
        Purchase.objects.order_by("bill_date").values_list("bill_date", flat=True).first(),
        SalaryPayment.objects.order_by("month").values_list("month", flat=True).first(),
    ]
    firsts = [d for d in firsts if d]
    return min(firsts) if firsts else today()


def pnl(period):
    start, end = period.start, period.end

    revenue_days = revenue_by_day(start, end)
    revenue = sum(revenue_days.values(), ZERO)
    gst_collected = (
        SaleOrder.objects.filter(date__range=(start, end), is_cancelled=False).aggregate(v=Sum("tax"))["v"] or ZERO
    )

    purchases = Purchase.objects.filter(bill_date__range=(start, end))
    inventory_total = purchases.aggregate(v=Sum("total"))["v"] or ZERO
    inv_labels = dict(InventoryCategory.choices)
    inventory_by_vendor = list(
        purchases.values("vendor__name").annotate(amount=Sum("total")).order_by("-amount")
    )
    inventory_by_category = [
        {"name": inv_labels.get(r["category"], r["category"]), "amount": r["amount"]}
        for r in purchases.values("category").annotate(amount=Sum("total")).order_by("-amount")
    ]

    all_expenses = DailyExpense.objects.filter(date__range=(start, end))
    # GST paid to the government isn't a cost: sales are already counted without GST.
    gst_paid = all_expenses.filter(item__category="gst").aggregate(v=Sum("amount"))["v"] or ZERO
    expenses = all_expenses.exclude(item__category="gst")
    expense_total = expenses.aggregate(v=Sum("amount"))["v"] or ZERO
    exp_labels = dict(ExpenseCategory.choices)
    exp_rows = list(expenses.values("item__category").annotate(amount=Sum("amount")).order_by("-amount"))
    expense_by_category = [
        {"name": exp_labels.get(r["item__category"], r["item__category"]), "amount": r["amount"]} for r in exp_rows
    ]
    food_expenses = sum((r["amount"] for r in exp_rows if r["item__category"] in FOOD_EXPENSE_CATEGORIES), ZERO)

    tracked_from = tracking_start()
    salary = salary_cost(start, end, estimate_from=tracked_from)
    salary_total = salary["total"]

    fixed = fixed_cost(start, end)
    fixed_total = fixed["total"]

    total_cost = inventory_total + expense_total + fixed_total + salary_total
    profit = revenue - total_cost
    food_cost = inventory_total + food_expenses

    # Per-bucket breakdown for the chart and table.
    def bucketise(rows, date_key, amount_key):
        out = [ZERO] * len(period.buckets)
        for r in rows:
            i = period.bucket_index(r[date_key])
            if i is not None:
                out[i] += r[amount_key] or ZERO
        return out

    rev_b = bucketise([{"d": d, "v": v} for d, v in revenue_days.items()], "d", "v")
    inv_b = bucketise(purchases.values("bill_date").annotate(v=Sum("total")), "bill_date", "v")
    exp_b = bucketise(expenses.values("date").annotate(v=Sum("amount")), "date", "v")
    sal_b = [allocate(salary["months"], b.start, b.end) for b in period.buckets]
    fix_b = [allocate(fixed["months"], b.start, b.end) for b in period.buckets]
    rows = []
    for i, b in enumerate(period.buckets):
        cost = inv_b[i] + exp_b[i] + fix_b[i] + sal_b[i]
        rows.append({
            "label": b.label,
            "start": b.start,
            "end": b.end,
            "revenue": rev_b[i],
            "inventory": inv_b[i],
            "expenses": exp_b[i],
            "fixed": fix_b[i],
            "salary": sal_b[i],
            "cost": cost,
            "profit": rev_b[i] - cost,
        })

    return {
        "revenue": revenue,
        "gst_collected": gst_collected,
        "gst_paid": gst_paid,
        "inventory": inventory_total,
        "inventory_by_vendor": inventory_by_vendor,
        "inventory_by_category": inventory_by_category,
        "expenses": expense_total,
        "expense_by_category": expense_by_category,
        "fixed": fixed_total,
        "fixed_by_head": fixed["by_head"],
        "salary": salary_total,
        "salary_actual": salary["actual"],
        "salary_estimated": salary["estimated"],
        "total_cost": total_cost,
        "profit": profit,
        "margin": (profit * 100 / revenue) if revenue else None,
        "food_cost": food_cost,
        "food_cost_pct": (food_cost * 100 / revenue) if revenue else None,
        "rows": rows,
        "days_with_sales": len(revenue_days),
        # Days that should have sales: from when tracking began up to today.
        "days_elapsed": max((min(end, today()) - max(start, tracked_from)).days + 1, 0),
    }
