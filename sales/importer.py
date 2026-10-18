"""
Import Petpooja sales exports (.xlsx, .xls or .csv).

Petpooja reports start with a few title rows (outlet name, report name, date
range) before the real header row, and end with a "Total" row. Column names
also vary a little between report types, so instead of fixed positions we:

  1. scan the first rows for the one that looks most like a header,
  2. map each header to a field using the synonym lists below,
  3. decide whether it is an orders/invoice report or an item-wise report.

When we get real sample exports, extending the synonym lists is usually all
that is needed.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import SaleItemLine, SaleOrder, SalePayment, SalesUpload

# Normalised header text -> field. Headers are lower-cased and stripped of
# punctuation/currency symbols before lookup, e.g. "My Amount (₹)" -> "my amount".
ORDER_FIELDS = {
    "invoice_no": ["invoice no", "invoice number", "bill no", "bill number", "order no", "order id", "order number", "invoice id"],
    "date": ["date", "order date", "invoice date", "bill date", "created", "created at", "created date", "date time", "order date time"],
    "time": ["time", "order time", "invoice time"],
    "order_type": ["order type", "type"],
    "source": ["area", "sub order type", "order from", "source", "channel", "order source"],
    "payment_mode": ["payment type", "payment mode", "payment method", "settlement mode", "mode of payment", "payment"],
    "payment_description": ["payment description", "payment details", "payment remarks"],
    "status": ["status", "order status"],
    "gross_amount": ["my amount", "sub total", "subtotal", "gross amount", "gross sales", "item total", "core amount"],
    "discount": ["discount", "total discount", "discount amount", "discounts"],
    "tax": ["total tax", "tax", "taxes", "gst", "total gst"],
    "delivery_charge": ["delivery charge", "delivery charges", "delivery fee"],
    "container_charge": ["container charge", "container charges", "packaging charge", "packaging charges", "packing charge", "packing charges"],
    "total": ["grand total", "total", "net amount", "final total", "total amount", "bill amount", "invoice amount", "net sales"],
}
ITEM_FIELDS = {
    "item_name": ["item", "item name", "items", "name", "product", "product name", "dish"],
    "category": ["category", "category name", "item category", "group"],
    "quantity": ["qty", "quantity", "total qty", "item qty", "sold qty", "no of items"],
    "amount": ["amount", "total", "total amount", "net amount", "sales", "item total", "total sales", "net sales", "price total", "gross amount", "my amount"],
    "date": ORDER_FIELDS["date"],
    "invoice_no": ORDER_FIELDS["invoice_no"],
}
SPLIT_TAX_PREFIXES = ("cgst", "sgst", "igst", "utgst", "vat", "cess")
TOTAL_ROW_WORDS = {"total", "grand total", "totals", "sub total", "overall total"}

DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y %I:%M %p", "%d-%m-%Y",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p", "%d/%m/%Y",
    "%d %b %Y %H:%M:%S", "%d %b %Y %I:%M:%S %p", "%d %b %Y %I:%M %p", "%d %b %Y %H:%M", "%d %b %Y", "%d %B %Y",
    "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %I:%M %p",
    "%d-%b-%Y", "%d-%b-%y", "%b %d, %Y", "%d.%m.%Y",
]


class SalesImportError(Exception):
    """Raised with a message that is safe to show to the person uploading."""


def norm(header):
    s = str(header or "").lower().replace("₹", " ").replace("rs.", " ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def to_decimal(value):
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    s = str(value).strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("INR", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if s in ("", "-", "--", "NA", "N/A"):
        return Decimal(0)
    try:
        v = Decimal(s)
    except InvalidOperation:
        return Decimal(0)
    return -v if neg else v


def to_datetime(value, xls_datemode=None):
    """Return (date, time-or-None) or (None, None)."""
    if value in (None, ""):
        return None, None
    if isinstance(value, datetime):
        t = value.time()
        return value.date(), (t if t != time(0) else None)
    if isinstance(value, date):
        return value, None
    if isinstance(value, (int, float)) and xls_datemode is not None:
        import xlrd

        dt = xlrd.xldate_as_datetime(value, xls_datemode)
        t = dt.time()
        return dt.date(), (t if t != time(0) else None)
    if isinstance(value, (int, float)) and 20000 < value < 80000:  # Excel serial date in a CSV
        dt = datetime(1899, 12, 30) + timedelta(days=float(value))
        return dt.date(), None
    s = re.sub(r"\s+", " ", str(value).strip())
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        has_time = "%H" in fmt or "%I" in fmt
        return dt.date(), (dt.time() if has_time else None)
    return None, None


# ---------------------------------------------------------------- reading files


def read_rows(fileobj, filename):
    """Return (rows, xls_datemode). rows is a list of lists of cell values."""
    name = filename.lower()
    data = fileobj.read()
    if name.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))], None
    if name.endswith(".xls"):
        import xlrd

        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as exc:  # noqa: BLE001 - xlrd raises many types
            raise SalesImportError(f"Could not open the .xls file: {exc}")
        sheet = book.sheet_by_index(0)
        return [sheet.row_values(i) for i in range(sheet.nrows)], book.datemode
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise SalesImportError(f"Could not open the Excel file: {exc}")
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows, None
    raise SalesImportError("Please upload an Excel (.xlsx / .xls) or CSV file exported from Petpooja.")


def _match(headers, fields):
    """Map field -> column index, preferring earlier synonyms (more specific)."""
    mapping = {}
    for fname, synonyms in fields.items():
        best = None
        for idx, h in enumerate(headers):
            if h in synonyms:
                rank = synonyms.index(h)
                if best is None or rank < best[0]:
                    best = (rank, idx)
        if best is not None:
            mapping[fname] = best[1]
    return mapping


def find_header(rows, scan=30):
    best_idx, best_score = None, 1
    all_synonyms = {s for syns in list(ORDER_FIELDS.values()) + list(ITEM_FIELDS.values()) for s in syns}
    for i, row in enumerate(rows[:scan]):
        headers = [norm(c) for c in row]
        score = sum(1 for h in headers if h in all_synonyms)
        if score > best_score:
            best_idx, best_score = i, score
    if best_idx is None:
        raise SalesImportError(
            "Couldn't find the column headings in this file. Expected columns such as "
            "'Invoice No', 'Date', 'Payment Type', 'Grand Total' or 'Item', 'Qty', 'Amount'."
        )
    return best_idx


def detect_report_type(headers):
    order_map = _match(headers, ORDER_FIELDS)
    item_map = _match(headers, ITEM_FIELDS)
    has_item = "item_name" in item_map and ("quantity" in item_map or "amount" in item_map)
    has_order = "total" in order_map and ("invoice_no" in order_map or "payment_mode" in order_map)
    if has_item and "quantity" in item_map:
        return "items", item_map
    if has_order:
        return "orders", order_map
    if has_item:
        return "items", item_map
    raise SalesImportError(
        "This doesn't look like a Petpooja orders or item-wise report. Found columns: "
        + ", ".join(h for h in headers if h)
    )


# ---------------------------------------------------------------- parsing


@dataclass
class ParseResult:
    report_type: str
    records: list = field(default_factory=list)
    skipped: int = 0
    notes: list = field(default_factory=list)


def _cell(row, idx):
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    return v.strip() if isinstance(v, str) else v


def _is_total_row(row):
    for v in row[:3]:
        if isinstance(v, str) and norm(v) in TOTAL_ROW_WORDS:
            return True
    return False


def parse(rows, xls_datemode=None, fallback_date=None):
    h_idx = find_header(rows)
    headers = [norm(c) for c in rows[h_idx]]
    report_type, mapping = detect_report_type(headers)
    result = ParseResult(report_type)

    split_tax_cols = [i for i, h in enumerate(headers) if h.split(" ")[0] in SPLIT_TAX_PREFIXES]

    if "date" not in mapping and fallback_date is None:
        raise SalesImportError(
            "This file has no date column. Pick the sales date in the form "
            "(export one day at a time from Petpooja for item-wise reports)."
        )
    if "date" not in mapping:
        result.notes.append(f"No date column — all rows recorded on {fallback_date:%d %b %Y}.")

    for row in rows[h_idx + 1:]:
        if not row or all(v in (None, "") for v in row) or _is_total_row(row):
            continue
        g = lambda f: _cell(row, mapping.get(f))  # noqa: E731

        # Petpooja "Part Payment": the bill's row is followed by one row per
        # payment (same order no., no date) holding the amount and its mode.
        if report_type == "orders" and result.records and g("date") in (None, ""):
            last = result.records[-1]
            if last["invoice_no"] and _invoice(g("invoice_no")) == last["invoice_no"]:
                mode = str(g("payment_mode") or "").strip()
                if mode:
                    last["split"].append((mode, to_decimal(g("total"))))
                continue

        d, t = to_datetime(g("date"), xls_datemode) if "date" in mapping else (fallback_date, None)
        if d is None:
            result.skipped += 1
            continue

        if report_type == "orders":
            total = to_decimal(g("total"))
            if total == 0 and not g("invoice_no"):
                result.skipped += 1
                continue
            if "time" in mapping and t is None:
                _, t = to_datetime(f"2000-01-01 {g('time')}") if g("time") else (None, None)
            tax = to_decimal(g("tax")) if "tax" in mapping else sum(
                (to_decimal(_cell(row, i)) for i in split_tax_cols), Decimal(0)
            )
            status = str(g("status") or "")
            result.records.append(dict(
                invoice_no=_invoice(g("invoice_no")),
                date=d,
                time=t,
                # "Dine In (T3)" -> "Dine In": the table number isn't an order type.
                order_type=re.sub(r"\s*\(.*\)\s*$", "", str(g("order_type") or "")),
                source=str(g("source") or ""),
                payment_mode=str(g("payment_mode") or "Unknown").strip() or "Unknown",
                status=status,
                is_cancelled=bool(re.search(r"cancel|void|reject|complimentary", status, re.I)),
                gross_amount=to_decimal(g("gross_amount")),
                discount=abs(to_decimal(g("discount"))),
                tax=tax,
                delivery_charge=to_decimal(g("delivery_charge")),
                container_charge=to_decimal(g("container_charge")),
                total=total,
                description=str(g("payment_description") or ""),
                split=[],
            ))
        else:
            name = str(g("item_name") or "").strip()
            if not name:
                result.skipped += 1
                continue
            result.records.append(dict(
                date=d,
                invoice_no=str(g("invoice_no") or "").removesuffix(".0"),
                item_name=name,
                category=str(g("category") or ""),
                quantity=to_decimal(g("quantity")),
                amount=to_decimal(g("amount")),
            ))

    if not result.records:
        raise SalesImportError("No sales rows were found below the header row.")
    if report_type == "orders":
        for r in result.records:
            _settle_payments(r)
    return result


def _invoice(value):
    return str(value or "").strip().removesuffix(".0")


def _settle_payments(r):
    """Turn an order's payment info into r["payments"]: [(mode, amount), ...].

    For part payments Petpooja leaves Grand Total at 0 and puts the real total
    in the description ("Total : 1076.00"); the split rows say how it was paid.
    """
    description, split = r.pop("description"), r.pop("split")
    if split:
        if not r["total"]:
            m = re.search(r"total\s*:?\s*(-?[\d,]+(?:\.\d+)?)", description, re.I)
            r["total"] = to_decimal(m.group(1)) if m else sum((a for _, a in split), Decimal(0))
        merged = {}
        for mode, amount in split:
            if amount:
                merged[mode] = merged.get(mode, Decimal(0)) + amount
        r["payments"] = list(merged.items()) or [(r["payment_mode"], r["total"])]
    else:
        r["payments"] = [(r["payment_mode"], r["total"])]


# ---------------------------------------------------------------- saving


def import_file(uploaded_file, user, fallback_date=None):
    """Parse and save an uploaded Petpooja export. Returns the SalesUpload.

    Re-uploading is safe: data of the same report type for the dates covered
    by the file is replaced, so corrected exports overwrite the old numbers.
    """
    rows, datemode = read_rows(uploaded_file, uploaded_file.name)
    result = parse(rows, datemode, fallback_date)
    dates = sorted({r["date"] for r in result.records})

    if result.report_type == "orders":
        # Drop exact duplicate invoices inside one file (some exports repeat rows).
        seen, unique = set(), []
        for r in result.records:
            key = (r["invoice_no"], r["date"]) if r["invoice_no"] else None
            if key and key in seen:
                result.skipped += 1
                continue
            if key:
                seen.add(key)
            unique.append(r)
        result.records = unique

    uploaded_file.seek(0)
    with transaction.atomic():
        upload = SalesUpload.objects.create(
            file=uploaded_file,
            original_name=uploaded_file.name[:255],
            report_type=result.report_type,
            start_date=dates[0],
            end_date=dates[-1],
            rows_imported=len(result.records),
            rows_skipped=result.skipped,
            log="\n".join(result.notes),
            created_by=user,
        )
        if result.report_type == "orders":
            replaced = SaleOrder.objects.filter(date__in=dates).delete()[1].get("sales.SaleOrder", 0)
            payments = [r.pop("payments") for r in result.records]
            orders = SaleOrder.objects.bulk_create(SaleOrder(upload=upload, **r) for r in result.records)
            SalePayment.objects.bulk_create(
                SalePayment(order=o, mode=mode, amount=amount)
                for o, pays in zip(orders, payments)
                for mode, amount in pays
            )
        else:
            replaced = SaleItemLine.objects.filter(date__in=dates).delete()[0]
            SaleItemLine.objects.bulk_create(SaleItemLine(upload=upload, **r) for r in result.records)
        if replaced:
            upload.log = (upload.log + f"\nReplaced {replaced} earlier rows for the same dates.").strip()
            upload.save(update_fields=["log"])
        # Earlier uploads whose rows have all been replaced by this one are no longer needed.
        rows_field = "orders" if result.report_type == "orders" else "items"
        for old in SalesUpload.objects.filter(report_type=result.report_type, **{f"{rows_field}__isnull": True}).exclude(pk=upload.pk):
            old.file.delete(save=False)
            old.delete()
    return upload

