"""Who put money in: Eatalley's own money vs each partner, across every kind of spend."""

from collections import defaultdict
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import redirect, render

from core.models import Payer
from core.periods import parse_date
from expenses.models import DailyExpense
from inventory.models import Purchase
from opening.models import OpeningCost
from payroll.models import SalaryPayment

ZERO = Decimal(0)

# (key, label, queryset, date field)
SECTIONS = [
    ("expenses", "Daily expenses", DailyExpense.objects, "date"),
    ("inventory", "Inventory bills", Purchase.objects, "bill_date"),
    ("salary", "Salaries", SalaryPayment.objects, "paid_on"),
    ("opening", "Opening costs", OpeningCost.objects, "date"),
]
AMOUNT = {"expenses": "amount", "inventory": "total", "salary": "amount", "opening": "amount"}


class PayerForm(forms.ModelForm):
    class Meta:
        model = Payer
        fields = ["name", "is_business"]
        labels = {"is_business": "This is Eatalley's own money (not a partner)"}


def paid_by_view(request):
    form = PayerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        p = form.save()
        messages.success(request, f"Added {p.name}. They now appear in every 'Paid by' list.")
        return redirect("reports:paid_by")

    start, end = parse_date(request.GET.get("start")), parse_date(request.GET.get("end"))
    rows = defaultdict(lambda: defaultdict(lambda: ZERO))
    totals = defaultdict(lambda: ZERO)
    for key, _, manager, date_field in SECTIONS:
        qs = manager.all()
        if start:
            qs = qs.filter(**{f"{date_field}__gte": start})
        if end:
            qs = qs.filter(**{f"{date_field}__lte": end})
        for r in qs.values("paid_by").annotate(v=Sum(AMOUNT[key])):
            rows[r["paid_by"]][key] += r["v"] or ZERO
            totals[key] += r["v"] or ZERO

    payers = {p.pk: p for p in Payer.objects.all()}
    table = []
    for pid, vals in rows.items():
        p = payers.get(pid)
        table.append({
            "payer": p,
            "name": p.name if p else "Not recorded",
            "is_business": bool(p and p.is_business),
            "values": [vals[k] for k, *_ in SECTIONS],
            "total": sum(vals.values(), ZERO),
        })
    table.sort(key=lambda r: (not r["is_business"], -r["total"]))
    grand = sum(totals.values(), ZERO)
    partners = [r for r in table if not r["is_business"] and r["payer"]]
    return render(request, "reports/paid_by.html", {
        "form": form,
        "sections": [label for _, label, *_ in SECTIONS],
        "table": table,
        "totals": [totals[k] for k, *_ in SECTIONS],
        "grand": grand,
        "partner_total": sum((r["total"] for r in partners), ZERO),
        "partner_average": (sum((r["total"] for r in partners), ZERO) / len(partners)) if partners else ZERO,
        "partners": partners,
        "start": start,
        "end": end,
    })
