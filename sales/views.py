from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.periods import VIEW_CHOICES, get_period

from .importer import SalesImportError, import_file
from .models import SalesUpload
from .services import sales_summary


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
