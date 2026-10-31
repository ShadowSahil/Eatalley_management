import csv

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.periods import VIEW_CHOICES, get_period, parse_date

from .importer import SalesImportError, import_file
from .models import SaleOrder, SalesUpload
from .services import customer_list, sales_summary


class UploadForm(forms.Form):
    file = forms.FileField(
        label="Petpooja export",
        help_text="Excel (.xlsx / .xls) or CSV, as downloaded from Petpooja Reports.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.xls,.csv"}),
    )
    sales_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Only needed if the report has no date column (e.g. a one-day item-wise report).",
    )


def dashboard(request):
    period = get_period(request.GET, default_kind="month")
    s = sales_summary(period)
    top_n = int(request.GET.get("top", 15)) if request.GET.get("top", "").isdigit() else 15
    return render(request, "sales/dashboard.html", {
        "period": period,
        "view_choices": VIEW_CHOICES,
        "s": s,
        "top_items": s["items"][:top_n] if top_n else s["items"],
        "show_all_items": top_n == 0,
        "chart": {
            "labels": [b.label for b in period.buckets],
            "values": [float(v) for v in s["trend"]],
            "payment": {
                "labels": [r["name"] for r in s["by_payment"]],
                "values": [float(r["amount"]) for r in s["by_payment"]],
            },
        },
        "last_upload": SalesUpload.objects.first(),
    })


def upload(request):
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            up = import_file(form.cleaned_data["file"], request.user, form.cleaned_data.get("sales_date"))
        except SalesImportError as exc:
            form.add_error("file", str(exc))
        else:
            span = f"{up.start_date:%d %b %Y}" + (f" – {up.end_date:%d %b %Y}" if up.end_date != up.start_date else "")
            messages.success(
                request,
                f"Imported {up.rows_imported} rows from the {up.get_report_type_display().lower()} for {span}."
                + (f" Skipped {up.rows_skipped} rows." if up.rows_skipped else ""),
            )
            view = "day" if up.start_date == up.end_date else "custom"
            return redirect(f"{reverse('sales:dashboard')}?view={view}&d={up.start_date}&start={up.start_date}&end={up.end_date}")
    return render(request, "sales/upload.html", {
        "form": form,
        "uploads": SalesUpload.objects.select_related("created_by")[:30],
    })


@require_POST
def upload_delete(request, pk):
    up = get_object_or_404(SalesUpload, pk=pk)
    n = up.rows_imported
    up.file.delete(save=False)
    up.delete()  # cascades to the orders / item rows it created
    messages.success(request, f"Removed {up.original_name} and its {n} rows.")
    return redirect("sales:upload")


CUSTOMER_SORTS = {
    "recent": ("Last visit", lambda c: (c["last"], c["orders"]), True),
    "orders": ("Most orders", lambda c: (c["orders"], c["spent"]), True),
    "spent": ("Most spent", lambda c: (c["spent"], c["orders"]), True),
    "name": ("Name", lambda c: (c["name"].lower(), c["phone"]), False),
}


def customers(request):
    """Customer names and numbers from the uploaded Petpooja order reports."""
    start, end = parse_date(request.GET.get("start")), parse_date(request.GET.get("end"))
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort") if request.GET.get("sort") in CUSTOMER_SORTS else "recent"
    rows = customer_list(start, end)
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        rows = [c for c in rows if q.lower() in c["name"].lower() or (digits and digits in c["phone"])]
    _, key, reverse_ = CUSTOMER_SORTS[sort]
    rows.sort(key=key, reverse=reverse_)

    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="eatalley-customers.csv"'
        w = csv.writer(resp)
        w.writerow(["Name", "Phone", "Orders", "Total spent", "First order", "Last order"])
        for c in rows:
            w.writerow([c["name"], c["phone"], c["orders"], c["spent"], c["first"], c["last"]])
        return resp

    orders = SaleOrder.objects.filter(is_cancelled=False)
    if start:
        orders = orders.filter(date__gte=start)
    if end:
        orders = orders.filter(date__lte=end)
    return render(request, "sales/customers.html", {
        "customers": rows,
        "with_phone": sum(1 for c in rows if c["phone"]),
        "repeat": sum(1 for c in rows if c["orders"] > 1),
        "orders_total": orders.count(),
        "orders_with_customer": orders.exclude(customer_name="", customer_phone="").count(),
        "sorts": [(k, v[0]) for k, v in CUSTOMER_SORTS.items()],
        "f": {"start": start, "end": end, "q": q, "sort": sort},
        "filtered": any([start, end, q]),
    })
