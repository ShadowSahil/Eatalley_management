import csv

from django.http import HttpResponse
from django.shortcuts import render

from core.periods import VIEW_CHOICES, get_period

from .services import pnl


def pnl_view(request):
    period = get_period(request.GET, default_kind="month")
    p = pnl(period)

    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="eatalley-pnl-{period.start}-{period.end}.csv"'
        w = csv.writer(resp)
        w.writerow(["Period", "Sales (excl. GST)", "Inventory", "Daily expenses", "Fixed costs", "Salaries", "Total cost", "Profit"])
        for r in p["rows"]:
            w.writerow([r["label"], r["revenue"], r["inventory"], r["expenses"], f"{r['fixed']:.2f}", f"{r['salary']:.2f}", f"{r['cost']:.2f}", f"{r['profit']:.2f}"])
        w.writerow(["Total", p["revenue"], p["inventory"], p["expenses"], p["fixed"], p["salary"], p["total_cost"], p["profit"]])
        return resp

    return render(request, "reports/pnl.html", {
        "period": period,
        "view_choices": VIEW_CHOICES,
        "p": p,
        "chart": {
            "labels": [r["label"] for r in p["rows"]],
            "revenue": [float(r["revenue"]) for r in p["rows"]],
            "cost": [float(r["cost"]) for r in p["rows"]],
            "profit": [float(r["profit"]) for r in p["rows"]],
        },
    })
