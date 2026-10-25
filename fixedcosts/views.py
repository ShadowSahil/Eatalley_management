from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.periods import add_months, parse_date, today
from core.templatetags.money import format_inr

from .forms import FixedCostForm, HeadForm
from .models import FixedCost, FixedCostHead

ZERO = Decimal(0)


def _month_from(request):
    raw = request.GET.get("month", "")
    d = parse_date(f"{raw}-01") if len(raw) == 7 else None
    return (d or today()).replace(day=1)


def _url(month):
    return f"{reverse('fixedcosts:index')}?month={month:%Y-%m}"


def _last_amount(head):
    last = head.payments.order_by("-month", "-paid_on").first()
    return last.amount if last else None


def index(request):
    month = _month_from(request)
    costs = FixedCost.objects.filter(month=month).select_related("head", "paid_by", "created_by").order_by("paid_on")
    paid = defaultdict(lambda: ZERO)
    for c in costs:
        paid[c.head_id] += c.amount

    rows = []
    for head in FixedCostHead.objects.all():
        if not head.is_active and head.id not in paid:
            continue
        rows.append({"head": head, "paid": paid.get(head.id, ZERO), "last": _last_amount(head)})

    return render(request, "fixedcosts/index.html", {
        "month": month,
        "prev_month": add_months(month, -1),
        "next_month": add_months(month, 1),
        "rows": rows,
        "costs": costs,
        "total": costs.aggregate(v=Sum("amount"))["v"] or ZERO,
        "missing": [r["head"] for r in rows if r["head"].is_active and not r["paid"]],
        "head_form": HeadForm(prefix="head"),
    })


def cost_form(request, pk=None):
    cost = get_object_or_404(FixedCost, pk=pk) if pk else None
    initial = {}
    if not cost:
        initial = {"month": _month_from(request), "paid_on": today()}
        head_id = request.GET.get("head", "")
        if head_id.isdigit():
            initial["head"] = int(head_id)
            head = FixedCostHead.objects.filter(pk=int(head_id)).first()
            if head and _last_amount(head) is not None:
                initial["amount"] = _last_amount(head)
    form = FixedCostForm(request.POST or None, request.FILES or None, instance=cost, initial=initial)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        if not cost:
            c.created_by = request.user
        c.save()
        messages.success(request, f"{'Saved' if cost else 'Added'} {c.head} for {c.month:%b %Y} — {format_inr(c.amount)}.")
        return redirect(_url(c.month))
    return render(request, "core/form_page.html", {
        "form": form,
        "title": "Edit fixed cost" if cost else "Add fixed cost",
        "back_url": _url(cost.month if cost else initial["month"]),
        "delete_url": reverse("fixedcosts:delete", args=[cost.pk]) if cost else None,
    })


@require_POST
def cost_delete(request, pk):
    c = get_object_or_404(FixedCost, pk=pk)
    c.delete()
    messages.success(request, f"Deleted {c.head} for {c.month:%b %Y} ({format_inr(c.amount)}).")
    return redirect(_url(c.month))


def head_add(request):
    form = HeadForm(request.POST or None, prefix="head")
    if request.method == "POST" and form.is_valid():
        h = form.save()
        messages.success(request, f"Added {h.name}. It now shows every month.")
        return redirect("fixedcosts:index")
    return render(request, "core/form_page.html", {"form": form, "title": "Add a fixed cost type", "back": "fixedcosts:index"})


def head_edit(request, pk):
    head = get_object_or_404(FixedCostHead, pk=pk)
    form = HeadForm(request.POST or None, instance=head)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved {head.name}.")
        return redirect("fixedcosts:index")
    return render(request, "core/form_page.html", {"form": form, "title": f"Edit {head.name}", "back": "fixedcosts:index"})
