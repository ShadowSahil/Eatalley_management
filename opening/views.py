import csv
from decimal import Decimal

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import Payer
from core.periods import parse_date
from core.templatetags.money import format_inr

from .forms import OpeningCostForm
from .models import OpeningCategory, OpeningCost

ZERO = Decimal(0)


def index(request):
    form = OpeningCostForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        cost = form.save(commit=False)
        cost.created_by = request.user
        cost.save()
        messages.success(request, f"Added {cost.description or cost.paid_to} — {format_inr(cost.amount)}.")
        return redirect("opening:index")

    qs = OpeningCost.objects.select_related("paid_by")
    start, end = parse_date(request.GET.get("start")), parse_date(request.GET.get("end"))
    category, payer_id, q = request.GET.get("category", ""), request.GET.get("paid_by", ""), request.GET.get("q", "").strip()
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    if category:
        qs = qs.filter(category=category)
    if payer_id.isdigit():
        qs = qs.filter(paid_by_id=int(payer_id))
    if q:
        qs = qs.filter(Q(description__icontains=q) | Q(paid_to__icontains=q))

    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="eatalley-opening-costs.csv"'
        w = csv.writer(resp)
        w.writerow(["Date", "Amount", "Category", "Paid to", "Description", "Paid by"])
        for c in qs.order_by("date"):
            w.writerow([c.date, c.amount, c.get_category_display(), c.paid_to, c.description, c.paid_by or ""])
        return resp

    total = qs.aggregate(v=Sum("amount"))["v"] or ZERO
    labels = dict(OpeningCategory.choices)
    by_category = [
        {"key": r["category"], "name": labels.get(r["category"], r["category"]), "amount": r["amount"], "n": r["n"]}
        for r in qs.values("category").annotate(amount=Sum("amount"), n=Count("id")).order_by("-amount")
    ]
    by_payer = [
        {"id": r["paid_by"], "name": r["paid_by__name"] or "Not recorded", "amount": r["amount"], "n": r["n"]}
        for r in qs.values("paid_by", "paid_by__name").annotate(amount=Sum("amount"), n=Count("id")).order_by("-amount")
    ]
    return render(request, "opening/index.html", {
        "form": form,
        "costs": qs[:1000],
        "count": qs.count(),
        "total": total,
        "by_category": by_category,
        "by_payer": by_payer,
        "categories": OpeningCategory.choices,
        "payers": Payer.objects.all(),
        "f": {"start": start, "end": end, "category": category, "paid_by": payer_id, "q": q},
        "filtered": any([start, end, category, payer_id, q]),
    })


def edit(request, pk):
    cost = get_object_or_404(OpeningCost, pk=pk)
    form = OpeningCostForm(request.POST or None, request.FILES or None, instance=cost)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("opening:index")
    return render(request, "core/form_page.html", {
        "form": form,
        "title": "Edit opening cost",
        "back": "opening:index",
        "delete_url": reverse("opening:delete", args=[cost.pk]),
    })


@require_POST
def delete(request, pk):
    cost = get_object_or_404(OpeningCost, pk=pk)
    cost.delete()
    messages.success(request, f"Deleted {cost.description or cost.paid_to} ({format_inr(cost.amount)}).")
    return redirect("opening:index")
