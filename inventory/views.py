import os
import re
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from core.periods import VIEW_CHOICES, get_period, today
from core.templatetags.money import format_inr

from .forms import LineFormSet, PurchaseForm, ScanForm, VendorForm, line_formset
from .models import InventoryCategory, Purchase, Vendor
from .pdfparse import guess_fields, read_pdf

ZERO = Decimal(0)
PENDING_DIR = "inventory/pending"
PENDING_TOKEN = re.compile(r"^[0-9a-f]{32}\.(pdf|jpg|jpeg|png)$")


def _pending_path(token):
    if token and PENDING_TOKEN.match(token):
        name = f"{PENDING_DIR}/{token}"
        if default_storage.exists(name):
            return name
    return None


def purchase_list(request):
    period = get_period(request.GET, default_kind="month")
    qs = Purchase.objects.filter(bill_date__range=(period.start, period.end)).select_related("vendor", "created_by")
    vendor_id = request.GET.get("vendor", "")
    category = request.GET.get("category", "")
    if vendor_id.isdigit():
        qs = qs.filter(vendor_id=int(vendor_id))
    if category:
        qs = qs.filter(category=category)

    total = qs.aggregate(v=Sum("total"))["v"] or ZERO
    by_vendor = qs.values("vendor__name").annotate(amount=Sum("total"), bills=Count("id")).order_by("-amount")
    cat_labels = dict(InventoryCategory.choices)
    by_category = [
        {"name": cat_labels.get(r["category"], r["category"]), "amount": r["amount"]}
        for r in qs.values("category").annotate(amount=Sum("total")).order_by("-amount")
    ]
    trend = [ZERO] * len(period.buckets)
    for r in qs.values("bill_date").annotate(amount=Sum("total")):
        i = period.bucket_index(r["bill_date"])
        if i is not None:
            trend[i] += r["amount"]
    unpaid = Purchase.objects.filter(is_paid=False)
    unpaid_by_vendor = unpaid.values("vendor__name").annotate(amount=Sum("total"), bills=Count("id")).order_by("-amount")

    return render(request, "inventory/list.html", {
        "period": period,
        "view_choices": VIEW_CHOICES,
        "purchases": qs,
        "total": total,
        "tax": qs.aggregate(v=Sum("tax_amount"))["v"] or ZERO,
        "by_vendor": by_vendor,
        "by_category": by_category,
        "chart": {"labels": [b.label for b in period.buckets], "values": [float(v) for v in trend]},
        "unpaid_total": unpaid.aggregate(v=Sum("total"))["v"] or ZERO,
        "unpaid_by_vendor": unpaid_by_vendor,
        "vendors": Vendor.objects.all(),
        "categories": InventoryCategory.choices,
        "vendor_id": vendor_id,
        "category": category,
    })


def _original_name(raw, token):
    """The uploaded file's own name (kept for the attached bill), with the scanned file's extension."""
    ext = token.rsplit(".", 1)[-1]
    try:
        base = get_valid_filename(os.path.splitext(raw or "")[0])[:80]
    except Exception:  # noqa: BLE001 - get_valid_filename raises on empty/odd names
        base = ""
    return f"{base or 'bill'}.{ext}"


def matching_purchases(vendor, total, bill_date, days=10):
    """Existing entries that are probably this same bill (e.g. a payment imported from the old sheet)."""
    if not (vendor and total):
        return Purchase.objects.none()
    qs = Purchase.objects.filter(vendor=vendor, total__gte=total - 1, total__lte=total + 1)
    if bill_date:
        qs = qs.filter(bill_date__range=(bill_date - timedelta(days=days), bill_date + timedelta(days=days)))
    return qs.order_by("-bill_date")


def covering_payments(vendor, total, bill_date):
    """Bigger payments, recorded without a bill, that this bill may be part of.

    e.g. one ₹24,191 JS Foods payment for "cheese 15-28 Sept" that settled several bills.
    Payments come after the bill, so look from a week before to ~6 weeks after it.
    """
    if not (vendor and total and bill_date):
        return Purchase.objects.none()
    return (
        Purchase.objects.filter(vendor=vendor, total__gt=total + 1, bill_file="", lines__isnull=True,
                                bill_date__range=(bill_date - timedelta(days=7), bill_date + timedelta(days=45)))
        .order_by("bill_date")
    )


def _covering_from_post(post):
    try:
        vendor = Vendor.objects.get(pk=int(post.get("vendor")))
        total = Decimal(post.get("total") or "0")
    except (Vendor.DoesNotExist, TypeError, ValueError, ArithmeticError):
        return []
    from core.periods import parse_date

    return list(covering_payments(vendor, total, parse_date(post.get("bill_date"))))


def _render_form(request, form, formset, purchase=None, pending=None, scan_note=None, pending_name="", matches=(),
                 lumps=()):
    return render(request, "inventory/purchase_form.html", {
        "form": form,
        "formset": formset,
        "purchase": purchase,
        "pending": pending,
        "pending_name": pending_name,
        "matches": matches,
        "lumps": lumps,
        "pending_url": default_storage.url(f"{PENDING_DIR}/{pending}") if pending else None,
        "scan_form": ScanForm(),
        "scan_note": scan_note,
        "vendor_categories": {v.pk: v.category for v in Vendor.objects.all()},
    })


@require_POST
def purchase_scan(request):
    """Read a bill PDF and pre-fill the add-bill form from it."""
    scan = ScanForm(request.POST, request.FILES)
    if not scan.is_valid():
        messages.error(request, "Choose a PDF to read.")
        return redirect("inventory:add")
    f = scan.cleaned_data["pdf"]
    ext = os.path.splitext(f.name)[1].lower().lstrip(".")
    if ext not in ("pdf", "jpg", "jpeg", "png"):
        messages.error(request, "Upload the bill as a PDF (or a JPG/PNG photo).")
        return redirect("inventory:add")
    token = f"{uuid.uuid4().hex}.{ext}"
    default_storage.save(f"{PENDING_DIR}/{token}", f)

    found = {}
    if ext == "pdf":
        with default_storage.open(f"{PENDING_DIR}/{token}", "rb") as fh:
            found = guess_fields(read_pdf(fh), list(Vendor.objects.filter(is_active=True)))
    lines = found.pop("lines", [])
    invoices = found.pop("invoices", [])
    initial = {"bill_date": today()}
    initial.update(found)
    if "vendor" in found:
        initial["vendor"] = found["vendor"].pk

    labels = {"vendor": "vendor", "bill_number": "bill no.", "bill_date": "date", "total": "total", "tax_amount": "GST"}
    got = [labels[k] for k in labels if k in found]
    if lines:
        got.append(f"{len(lines)} items")
    if got:
        note = f"Read from the PDF: {', '.join(got)}. Please check these before saving."
        if len(invoices) > 1:
            parts = " + ".join(format_inr(i["total"], 2) for i in invoices)
            note += f" This PDF has {len(invoices)} invoices ({parts}); they are saved together as one bill."
        lines_total = sum((ln["amount"] for ln in lines), ZERO)
        bill_total, gst = found.get("total"), found.get("tax_amount") or ZERO
        if lines and bill_total and abs(lines_total - bill_total) > 1:
            if abs(lines_total + gst - bill_total) <= 1:
                note += " The item amounts are before GST."
            else:
                note += f" Note: the items add up to {format_inr(lines_total, 2)}, not the bill total."
    elif ext == "pdf":
        note = "Couldn't read text from this PDF (it may be a scan). Please fill in the details — the file will still be attached."
    else:
        note = "Photo attached. Please fill in the details from the bill."

    form = PurchaseForm(initial=initial)
    formset = line_formset(extra=max(len(lines), 4))(initial=lines)
    matches = list(matching_purchases(found.get("vendor"), found.get("total"), found.get("bill_date")))
    lumps = [] if matches else list(covering_payments(found.get("vendor"), found.get("total"), found.get("bill_date")))
    return _render_form(request, form, formset, pending=token, scan_note=note, pending_name=f.name,
                        matches=matches, lumps=lumps)


@require_POST
def purchase_attach(request, pk):
    """Put a scanned bill on an entry that already exists instead of adding it twice.

    Fills in what the existing entry lacks (file, bill number, GST, items) and
    moves it to the bill's own date; payment details are kept.
    """
    purchase = get_object_or_404(Purchase, pk=pk)
    token = request.POST.get("pending")
    path = _pending_path(token)
    if not path:
        messages.error(request, "The uploaded bill has expired — please read it again.")
        return redirect("inventory:add")
    found = {}
    if token.endswith(".pdf"):
        with default_storage.open(path, "rb") as fh:
            found = guess_fields(read_pdf(fh), [purchase.vendor])
    with transaction.atomic():
        if not purchase.bill_file:
            with default_storage.open(path, "rb") as fh:
                purchase.bill_file.save(_original_name(request.POST.get("pending_name"), token), File(fh), save=False)
        if found.get("bill_number") and not purchase.bill_number:
            purchase.bill_number = found["bill_number"][:50]
        if found.get("bill_date"):
            purchase.bill_date = found["bill_date"]
        if found.get("tax_amount") and not purchase.tax_amount:
            purchase.tax_amount = found["tax_amount"]
        purchase.save()
        if found.get("lines") and not purchase.lines.exists():
            for ln in found["lines"]:
                purchase.lines.create(**ln)
    default_storage.delete(path)
    messages.success(request, f"Attached the bill to the existing {purchase.vendor} entry ({format_inr(purchase.total, 2)}).")
    return redirect("inventory:edit", pk=purchase.pk)


def purchase_form(request, pk=None):
    purchase = get_object_or_404(Purchase, pk=pk) if pk else None
    pending = request.POST.get("pending") if request.method == "POST" else None
    pending_path = _pending_path(pending)

    if request.method == "POST":
        form = PurchaseForm(request.POST, request.FILES, instance=purchase)
        # A bound formset sizes itself from the posted TOTAL_FORMS, however many lines were read.
        formset = LineFormSet(request.POST, instance=purchase or Purchase())
        if form.is_valid() and formset.is_valid():
            lines_total = sum(
                (f.cleaned_data["amount"] for f in formset.forms
                 if f.cleaned_data and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("amount")),
                ZERO,
            )
            lump = None
            if not purchase and (request.POST.get("part_of") or "").isdigit():
                lump = Purchase.objects.filter(pk=int(request.POST["part_of"]), vendor=form.cleaned_data["vendor"]).first()
            bill_total = form.cleaned_data.get("total") or lines_total
            if form.cleaned_data.get("total") in (None, "") and not lines_total:
                form.add_error("total", "Enter the bill total (or the lines below).")
            elif lump and bill_total > lump.total + 1:
                form.add_error("total", f"This bill is bigger than the {format_inr(lump.total, 2)} payment it was matched to.")
            else:
                with transaction.atomic():
                    obj = form.save(commit=False)
                    if obj.total in (None, ""):
                        obj.total = lines_total
                    if not purchase:
                        obj.created_by = request.user
                    if lump:
                        # The bill was settled by that earlier payment: carry its payment details over
                        # and take this bill's amount off it, so nothing is counted twice.
                        obj.is_paid, obj.paid_on = True, lump.paid_on or lump.bill_date
                        obj.payment_mode, obj.paid_by = lump.payment_mode, lump.paid_by or obj.paid_by
                        lump.total -= obj.total
                        if lump.total <= 1:
                            lump.delete()
                        else:
                            lump.notes = f"{lump.notes} · {format_inr(obj.total, 2)} moved to bill {obj.bill_number or obj.bill_date}"[:300]
                            lump.save(update_fields=["total", "notes"])
                    if not obj.bill_file and pending_path:
                        with default_storage.open(pending_path, "rb") as fh:
                            obj.bill_file.save(_original_name(request.POST.get("pending_name"), pending), File(fh), save=False)
                    obj.save()
                    formset.instance = obj
                    formset.save()
                if pending_path:
                    default_storage.delete(pending_path)
                messages.success(request, f"{'Updated' if purchase else 'Saved'} {obj.vendor} bill — {format_inr(obj.total, 2)}.")
                if "add_another" in request.POST:
                    return redirect("inventory:add")
                return redirect(f"{reverse('inventory:list')}?view=month&d={obj.bill_date.isoformat()}")
    else:
        form = PurchaseForm(instance=purchase, initial=None if purchase else {"bill_date": today()})
        formset = LineFormSet(instance=purchase or Purchase())
    return _render_form(request, form, formset, purchase, pending if pending_path else None,
                        pending_name=request.POST.get("pending_name", ""),
                        lumps=_covering_from_post(request.POST) if request.method == "POST" and not purchase else ())


@require_POST
def purchase_delete(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    purchase.delete()
    messages.success(request, f"Deleted {purchase.vendor} bill ({format_inr(purchase.total, 2)}).")
    return redirect("inventory:list")


@require_POST
def purchase_mark_paid(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    purchase.is_paid = True
    purchase.paid_on = purchase.paid_on or today()
    purchase.save(update_fields=["is_paid", "paid_on"])
    messages.success(request, f"Marked {purchase.vendor} bill {purchase.bill_number or ''} as paid.")
    return redirect(request.POST.get("next") or "inventory:list")


def vendors(request):
    form = VendorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        v = form.save()
        messages.success(request, f"Added vendor {v.name}.")
        return redirect("inventory:vendors")
    vendor_list = Vendor.objects.annotate(
        bills=Count("purchases"),
        spent_fy=Sum("purchases__total", filter=Q(purchases__bill_date__gte=get_period({"view": "fy"}).start)),
        unpaid=Sum("purchases__total", filter=Q(purchases__is_paid=False)),
    )
    return render(request, "inventory/vendors.html", {"form": form, "vendors": vendor_list})


def vendor_edit(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk)
    form = VendorForm(request.POST or None, instance=vendor)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved {vendor.name}.")
        return redirect("inventory:vendors")
    return render(request, "core/form_page.html", {"form": form, "title": f"Edit vendor: {vendor.name}", "back": "inventory:vendors"})
