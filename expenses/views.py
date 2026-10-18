import csv
import io
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import Payer
from core.periods import VIEW_CHOICES, get_period, parse_date, today
from core.templatetags.money import format_inr

from .forms import DailyExpenseForm, ExpenseItemForm, ImportFileForm
from .models import PAYMENT_MODES, UNIT_CHOICES, DailyExpense, ExpenseCategory, ExpenseItem

ZERO = Decimal(0)
BLANK_ROWS = 3


def _last_rates():
    """Most recent per-unit price paid for each item, to pre-fill amounts."""
    rates = {}
    recent = (
        DailyExpense.objects.filter(quantity__gt=0, date__gte=today() - timedelta(days=120))
        .order_by("-date", "-created_at")
        .values("item_id", "amount", "quantity")
    )
    for r in recent:
        if r["item_id"] not in rates:
            rates[r["item_id"]] = (r["amount"] / r["quantity"]).quantize(Decimal("0.01"))
    return rates


def _decimal(value):
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    return Decimal(value)


def entry(request):
    """The everyday page: pick a date (today by default) and add expense rows."""
    day = parse_date(request.GET.get("date") or request.POST.get("date"), today())
    rows, errors = [], []

    if request.method == "POST":
        fields = ["item", "qty", "amount", "mode", "paid_by", "note", "new_name", "new_unit", "new_category"]
        cols = {f: request.POST.getlist(f) for f in fields}
        n = max(len(v) for v in cols.values())
        cols = {f: v + [""] * (n - len(v)) for f, v in cols.items()}
        items = {str(i.pk): i for i in ExpenseItem.objects.filter(is_active=True)}
        payers = {str(p.pk): p for p in Payer.objects.filter(is_active=True)}
        to_create = []

        if day > today():
            errors.append("The date can't be in the future.")

        for i in range(n):
            row = {f: cols[f][i].strip() for f in fields}
            row["error"] = ""
            rows.append(row)
            if not (row["item"] or row["qty"] or row["amount"] or row["new_name"]):
                continue  # untouched blank row
            try:
                qty = _decimal(row["qty"])
                amount = _decimal(row["amount"])
            except InvalidOperation:
                row["error"] = "Quantity and amount must be numbers."
                continue
            if row["item"] == "__new__":
                if not row["new_name"]:
                    row["error"] = "Type the new item's name."
                    continue
                item = None
            elif row["item"] in items:
                item = items[row["item"]]
            else:
                row["error"] = "Choose an item."
                continue
            if amount is None or amount <= 0:
                row["error"] = "Enter the amount paid."
                continue
            if qty is not None and qty < 0:
                row["error"] = "Quantity can't be negative."
                continue
            to_create.append((row, item, qty, amount))

        if any(r["error"] for r in rows):
            errors.append("Nothing was saved. Fix the highlighted rows and save again.")
        elif not to_create and not errors:
            errors.append("Add at least one item.")

        if not errors:
            with transaction.atomic():
                total = ZERO
                for row, item, qty, amount in to_create:
                    if item is None:
                        name = " ".join(row["new_name"].split())
                        item = ExpenseItem.objects.filter(name__iexact=name).first() or ExpenseItem.objects.create(
                            name=name,
                            unit=row["new_unit"] if row["new_unit"] in dict(UNIT_CHOICES) else "nos",
                            category=row["new_category"] if row["new_category"] in ExpenseCategory.values else "other",
                        )
                    DailyExpense.objects.create(
                        date=day,
                        item=item,
                        quantity=qty,
                        amount=amount,
                        payment_mode=row["mode"] if row["mode"] in dict(PAYMENT_MODES) else "cash",
                        paid_by=payers.get(row["paid_by"]) or Payer.default(),
                        note=row["note"][:200],
                        created_by=request.user,
                    )
                    total += amount
            messages.success(
                request,
                f"Saved {len(to_create)} expense{'s' if len(to_create) != 1 else ''} for {day:%d %b} ({format_inr(total, 2)}).",
            )
            return redirect(f"{reverse('expenses:entry')}?date={day.isoformat()}")

    default_payer = Payer.default()
    if not rows:
        rows = [{"mode": "cash", "paid_by": str(default_payer.pk) if default_payer else "", "error": ""}
                for _ in range(BLANK_ROWS)]

    day_qs = DailyExpense.objects.filter(date=day).select_related("item", "created_by", "paid_by")
    month_total = DailyExpense.objects.filter(
        date__gte=day.replace(day=1), date__lte=day
    ).aggregate(v=Sum("amount"))["v"] or ZERO
    rates = _last_rates()
    items = list(ExpenseItem.objects.filter(is_active=True))
    for it in items:
        it.last_rate = rates.get(it.pk)

    return render(request, "expenses/entry.html", {
        "day": day,
        "is_today": day == today(),
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1) if day < today() else None,
        "today": today(),
        "rows": rows,
        "errors": errors,
        "items": items,
        "units": UNIT_CHOICES,
        "categories": ExpenseCategory.choices,
        "modes": PAYMENT_MODES,
        "payers": Payer.objects.filter(is_active=True),
        "default_payer": str(default_payer.pk) if default_payer else "",
        "entries": day_qs,
        "day_total": day_qs.aggregate(v=Sum("amount"))["v"] or ZERO,
        "month_total": month_total,
    })


def expense_list(request):
    period = get_period(request.GET, default_kind="month")
    qs = DailyExpense.objects.filter(date__range=(period.start, period.end)).select_related("item", "created_by", "paid_by")
    category = request.GET.get("category", "")
    item_id = request.GET.get("item", "")
    payer_id = request.GET.get("paid_by", "")
    if payer_id.isdigit():
        qs = qs.filter(paid_by_id=int(payer_id))
    if category:
        qs = qs.filter(item__category=category)
    if item_id.isdigit():
        qs = qs.filter(item_id=int(item_id))

    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="eatalley-expenses-{period.start}-{period.end}.csv"'
        w = csv.writer(resp)
        w.writerow(["Date", "Item", "Category", "Quantity", "Unit", "Amount", "Mode", "Paid by", "Note", "Added by"])
        for e in qs.order_by("date", "created_at"):
            w.writerow([
                e.date, e.item.name, e.item.get_category_display(), e.quantity or "", e.item.unit,
                e.amount, e.get_payment_mode_display(), e.paid_by or "", e.note,
                (e.created_by.get_full_name() or e.created_by.username) if e.created_by else "",
            ])
        return resp

    total = qs.aggregate(v=Sum("amount"))["v"] or ZERO
    by_item = (
        qs.values("item__id", "item__name", "item__unit")
        .annotate(qty=Sum("quantity"), amount=Sum("amount"), n=Count("id"))
        .order_by("-amount")
    )
    cat_labels = dict(ExpenseCategory.choices)
    by_category = [
        {"name": cat_labels.get(r["item__category"], r["item__category"]), "key": r["item__category"], "amount": r["amount"]}
        for r in qs.values("item__category").annotate(amount=Sum("amount")).order_by("-amount")
    ]
    by_mode = [
        {"name": dict(PAYMENT_MODES).get(r["payment_mode"]) or "Mode not recorded", "amount": r["amount"]}
        for r in qs.values("payment_mode").annotate(amount=Sum("amount")).order_by("-amount")
    ]
    trend = [ZERO] * len(period.buckets)
    for r in qs.values("date").annotate(amount=Sum("amount")):
        i = period.bucket_index(r["date"])
        if i is not None:
            trend[i] += r["amount"]

    return render(request, "expenses/list.html", {
        "period": period,
        "view_choices": VIEW_CHOICES,
        "entries": qs[:500],
        "entry_count": qs.count(),
        "total": total,
        "by_item": by_item,
        "by_category": by_category,
        "by_mode": by_mode,
        "chart": {
            "labels": [b.label for b in period.buckets],
            "values": [float(v) for v in trend],
        },
        "categories": ExpenseCategory.choices,
        "all_items": ExpenseItem.objects.all(),
        "category": category,
        "item_id": item_id,
        "payers": Payer.objects.all(),
        "payer_id": payer_id,
        "per_day": total / period.days if period.days else ZERO,
    })


def expense_edit(request, pk):
    expense = get_object_or_404(DailyExpense, pk=pk)
    form = DailyExpenseForm(request.POST or None, instance=expense)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Expense updated.")
        return redirect(f"{reverse('expenses:entry')}?date={expense.date.isoformat()}")
    return render(request, "core/form_page.html", {
        "form": form,
        "title": "Edit expense",
        "back_url": f"{reverse('expenses:entry')}?date={expense.date.isoformat()}",
        "delete_url": reverse("expenses:delete", args=[expense.pk]),
        "meta": f"Added by {expense.created_by or 'unknown'} on {expense.created_at:%d %b %Y, %I:%M %p}",
    })


@require_POST
def expense_delete(request, pk):
    expense = get_object_or_404(DailyExpense, pk=pk)
    day = expense.date
    expense.delete()
    messages.success(request, f"Deleted {expense.item} ({format_inr(expense.amount, 2)}).")
    return redirect(f"{reverse('expenses:entry')}?date={day.isoformat()}")


def items(request):
    form = ExpenseItemForm(request.POST or None, prefix="new")
    if request.method == "POST" and form.is_valid():
        item = form.save()
        messages.success(request, f"Added {item.name}.")
        return redirect("expenses:items")
    q = request.GET.get("q", "").strip()
    qs = ExpenseItem.objects.annotate(
        uses=Count("expenses"),
        spent_30=Sum("expenses__amount", filter=Q(expenses__date__gte=today() - timedelta(days=30))),
        last_used=Max("expenses__date"),
    )
    if q:
        qs = qs.filter(name__icontains=q)
    rates = _last_rates()
    item_list = list(qs)
    for it in item_list:
        it.last_rate = rates.get(it.pk)
    return render(request, "expenses/items.html", {
        "form": form,
        "items": item_list,
        "import_form": ImportFileForm(),
        "q": q,
    })


def item_edit(request, pk):
    item = get_object_or_404(ExpenseItem, pk=pk)
    form = ExpenseItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved {item.name}.")
        return redirect("expenses:items")
    return render(request, "core/form_page.html", {
        "form": form,
        "title": f"Edit item: {item.name}",
        "back": "expenses:items",
    })


def _match_choice(text, choices, default):
    t = (text or "").strip().lower()
    if not t:
        return default
    for value, label in choices:
        if t == value.lower() or t == label.lower():
            return value
    for value, label in choices:
        if t in label.lower() or label.lower().split(" ")[0] in t:
            return value
    return default


@require_POST
def items_import(request):
    """Bulk-add items from an Excel/CSV list (e.g. the last two months of purchases)."""
    form = ImportFileForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Choose a file to import.")
        return redirect("expenses:items")
    f = form.cleaned_data["file"]
    name = f.name.lower()
    try:
        if name.endswith(".csv"):
            rows = list(csv.reader(io.StringIO(f.read().decode("utf-8-sig", errors="replace"))))
        elif name.endswith((".xlsx", ".xlsm")):
            import openpyxl

            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        else:
            messages.error(request, "Please upload a .xlsx or .csv file.")
            return redirect("expenses:items")
    except Exception as exc:  # noqa: BLE001 - show any parse failure to the user
        messages.error(request, f"Couldn't read that file: {exc}")
        return redirect("expenses:items")

    rows = [r for r in rows if r and any(c not in (None, "") for c in r)]
    if not rows:
        messages.error(request, "The file is empty.")
        return redirect("expenses:items")
    header = [str(c or "").strip().lower() for c in rows[0]]

    def col(*names):
        for n in names:
            if n in header:
                return header.index(n)
        return None

    name_col = col("item", "item name", "items", "name", "particulars", "description")
    has_header = name_col is not None
    name_col = name_col if has_header else 0
    unit_col = col("unit", "uom", "units")
    cat_col = col("category", "type", "group")

    existing = {i.name.lower() for i in ExpenseItem.objects.all()}
    created, skipped = [], 0
    for r in rows[1:] if has_header else rows:
        raw = r[name_col] if name_col < len(r) else None
        item_name = " ".join(str(raw or "").split())
        if not item_name or item_name.lower() in existing or item_name.lower() in ("total", "grand total"):
            skipped += 1
            continue
        unit = _match_choice(r[unit_col] if unit_col is not None and unit_col < len(r) else "", UNIT_CHOICES, "nos")
        category = _match_choice(r[cat_col] if cat_col is not None and cat_col < len(r) else "", ExpenseCategory.choices, "other")
        ExpenseItem.objects.create(name=item_name[:100], unit=unit, category=category)
        existing.add(item_name.lower())
        created.append(item_name)

    messages.success(
        request,
        f"Imported {len(created)} new item{'s' if len(created) != 1 else ''}"
        + (f"; skipped {skipped} duplicate or blank rows." if skipped else "."),
    )
    return redirect("expenses:items")
