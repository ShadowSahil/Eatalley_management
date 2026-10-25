"""
Best-effort reading of vendor bill PDFs.

Most GST invoices (Hyperpure, Tally-made bills) are ruled tables, so we read
the tables first:
  * "label / value" cells give the invoice number, date and order number,
  * the item table (Description · Qty · UoM · ... · Total) gives the lines,
  * its "Total" row gives the bill total and GST.
A PDF can hold several invoices (Hyperpure puts a Bill of Supply and a Tax
Invoice for one order in one file); they are added up into one bill.

If a PDF has no usable tables we fall back to searching the text for common
labels (Invoice No, Date, Grand Total). Scanned/photographed bills have no
text layer and simply return nothing; those are entered by hand.
"""

import re
from decimal import Decimal, InvalidOperation

from sales.importer import to_datetime

ZERO = Decimal(0)
AMOUNT = r"(?:₹|rs\.?|inr)?\s*(-?[\d,]+(?:\.\d{1,2})?)"

# ------------------------------------------------------------------ reading


def read_pdf(fileobj, max_pages=10):
    """[{"text": str, "tables": [[row, ...], ...]}, ...] — empty list if unreadable."""
    import pdfplumber

    try:
        with pdfplumber.open(fileobj) as pdf:
            return [
                {
                    "text": p.extract_text() or "",
                    "tables": [_unstack(p, t) for t in p.find_tables()],
                }
                for p in pdf.pages[:max_pages]
            ]
    except Exception:  # noqa: BLE001 - corrupt or encrypted PDFs
        return []


STACK_STOP = re.compile(r"\b(igst|cgst|sgst|output|round\s*off|less|total)\b", re.I)


def _unstack(page, table):
    """Split rows where several items share one cell (Tally / Busy bills).

    Those bills draw no line between items, so serial numbers "1\n2\n3" sit in
    one cell, and descriptions wrap over several lines. Each line is given to
    the item whose serial number starts at or above it on the page.
    """
    rows = table.extract()
    out = []
    for row, trow in zip(rows, table.rows):
        serials = [s.strip() for s in str(row[0] or "").split("\n") if s.strip()]
        if len(serials) < 2 or not all(s.isdigit() for s in serials):
            out.append(row)
            continue
        cells = trow.cells

        def lines_in(bbox):
            x0, top, x1, bottom = bbox
            region = page.within_bbox((x0 - 0.5, top - 0.5, x1 + 0.5, bottom + 0.5))
            return [(ln["top"], ln["text"].strip()) for ln in region.extract_text_lines()]

        starts = [top for top, text in lines_in(cells[0]) if text.isdigit()]
        if len(starts) != len(serials):
            out.append(row)
            continue
        items = [[""] * len(row) for _ in starts]
        for ci, bbox in enumerate(cells):
            if bbox is None:
                continue
            for top, text in lines_in(bbox):
                if not text or STACK_STOP.search(text):
                    continue
                i = max((k for k, s in enumerate(starts) if top >= s - 3), default=0)
                items[i][ci] = f"{items[i][ci]}\n{text}".strip()
        out.extend(items)
    return out


def extract_text(fileobj, max_pages=6):
    return "\n".join(p["text"] for p in read_pdf(fileobj, max_pages))


# ------------------------------------------------------------------ helpers


def _clean(cell):
    return " ".join(str(cell or "").split())


def _label(cell):
    """Normalise a header/label cell: 'Tax Amount\\n(CGST+SGST)' -> 'tax amount'."""
    s = _clean(cell).lower().replace("₹", " ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9# ]+", " ", s)
    return " ".join(s.split())


def _num(cell):
    """'1,234.50' -> Decimal; '8.6+8.6+0' (CGST+SGST+IGST) -> 17.2; '30.000 kgs' -> 30; blanks -> None."""
    s = re.sub(r"\(cid:\d+\)", "", str(cell or "")).replace(",", "").replace("₹", "").replace("\n", "")
    parts = [p.strip() for p in s.split("+") if p.strip()]
    if not parts:
        return None
    total = ZERO
    for p in parts:
        m = re.match(r"\(?(-?\d+(?:\.\d+)?)\)?", p)
        if not m:
            return None
        total += Decimal(m.group(1))
    return total


def _date(s):
    if not s:
        return None
    s = re.sub(r"[.]", "-", str(s).strip())
    s = re.sub(r"\s+", "-", s)
    d, _ = to_datetime(s)
    if d is None:
        parts = s.split("-")
        if len(parts) == 3 and len(parts[2]) == 2:
            d, _ = to_datetime(f"{parts[0]}-{parts[1]}-20{parts[2]}")
    return d


# ------------------------------------------------------------------ tables

KEY_LABELS = {
    "bill_number": {"invoice number", "invoice no", "inv no", "bill no", "bill number", "invoice #", "tax invoice no"},
    "bill_date": {"invoice date", "bill date", "date", "dated", "inv date"},
    "order_no": {"order no", "order number", "order id"},
}
COLS = {
    "description": ["description of goods", "description of goods services", "description", "item description",
                    "item name", "item", "particulars", "product", "product name", "goods"],
    "quantity": ["qty", "quantity", "billed qty", "qty billed"],
    "unit": ["uom", "unit", "per", "units"],
    # The line value we keep is the one that adds up to the bill total (incl. GST).
    "amount": ["total", "total amount", "line total", "amount incl tax", "net amount", "amount", "value", "taxable amount"],
    "tax": ["tax amount", "total tax", "gst amount", "tax", "gst"],
    "taxable": ["taxable amount", "taxable value"],
}
TOTAL_WORDS = {"total", "grand total", "sub total", "subtotal", "total amount", "invoice total"}


def _key_values(tables):
    """Find 'Invoice Number\\nZHPUP27-00216312' style cells."""
    found = {}
    for table in tables:
        for row in table:
            for cell in row:
                if not cell or "\n" not in str(cell):
                    continue
                label, _, value = str(cell).partition("\n")
                label, value = _label(label), _clean(value.split("\n")[0])
                if not value or value == "-":
                    continue
                for key, labels in KEY_LABELS.items():
                    if label in labels and key not in found:
                        found[key] = value
    return found


def _item_columns(row):
    labels = [_label(c) for c in row]
    cols = {}
    for key, names in COLS.items():
        best = None
        for i, lab in enumerate(labels):
            if lab in names and (best is None or names.index(lab) < best[0]):
                best = (names.index(lab), i)
        if best:
            cols[key] = best[1]
    if "description" in cols and "amount" in cols:
        if cols.get("taxable") == cols["amount"]:
            cols.pop("taxable")
        return cols
    return None


def _drop_tax_lines(row, cols):
    """A single item sharing its cell with the "IGST OUTPUT / Round Off" lines below it (Sunrise bills).

    "FLOUR ...\\nIGST OUTPUT\\nRound Off" | "9,750.00\\n487.50\\n0.50" -> "FLOUR ..." | "9,750.00".
    Several items in one cell are split earlier by _unstack.
    """
    desc_lines = str(row[cols["description"]] or "").split("\n")
    cut = next((i for i, ln in enumerate(desc_lines) if i and STACK_STOP.search(ln)), None)
    if cut is None:
        return row
    row = list(row)
    row[cols["description"]] = "\n".join(desc_lines[:cut])
    amounts = [ln for ln in str(row[cols["amount"]] or "").split("\n") if ln.strip()]
    row[cols["amount"]] = amounts[0] if amounts else ""
    return row


def _read_item_table(table, cols=None):
    """Return (cols, lines, totals) from one table; cols None if it isn't an item table."""
    start = 0
    if cols is None:
        for i, row in enumerate(table):
            cols = _item_columns(row)
            if cols:
                start = i + 1
                break
        else:
            return None, [], {}
    lines, totals = [], {}
    width = max(cols.values())
    for row in table[start:]:
        if len(row) <= width:
            continue
        row = _drop_tax_lines(row, cols)
        desc = _clean(row[cols["description"]])
        if not desc:
            continue
        if _label(desc) in TOTAL_WORDS:
            totals = {
                "total": _num(row[cols["amount"]]),
                "tax": _num(row[cols["tax"]]) if "tax" in cols else None,
            }
            break
        amount = _num(row[cols["amount"]])
        if amount is None:
            continue
        unit = _clean(row[cols["unit"]]) if "unit" in cols else ""
        lines.append({
            "description": desc[:150],
            "quantity": _num(row[cols["quantity"]]) if "quantity" in cols else None,
            "unit": unit[:10],
            "amount": amount,
        })
    return cols, lines, totals


# ------------------------------------------------------------------ text fallback

TOTAL_LABELS = [
    r"grand\s*total",
    r"net\s*(?:amount\s*)?payable",
    r"amount\s*payable",
    r"invoice\s*(?:total|value|amount)",
    r"net\s*amount",
    r"total\s*amount",
    r"bill\s*amount",
    r"total\s*(?:inr|rs\.?)?\s*:?",
]
TAX_LABELS = [r"total\s*(?:gst|tax)(?:\s*amount)?", r"gst\s*amount"]
SPLIT_TAX = r"\b(?:cgst|sgst|igst)\b[^\n]*?" + AMOUNT + r"\s*$"
BILL_NO = re.compile(
    r"(?:tax\s*invoice|invoice|bill|inv)\s*(?:number|num|no)\b\.?\s*[:\-#]?\s*([A-Z0-9][A-Z0-9\-/]{2,30})",
    re.I,
)
DATE_LABELLED = re.compile(
    r"(?:invoice|bill|inv)?\s*date\s*[:\-]?\s*(\d{1,2}[-/. ](?:\d{1,2}|[A-Za-z]{3,9})[-/. ]\d{2,4})",
    re.I,
)
DATE_ANY = re.compile(r"\b(\d{1,2}[-/. ](?:\d{1,2}|[A-Za-z]{3})[-/. ]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
SKIP_LINE = re.compile(r"\b(qty|quantity|no\.? of items|total items|in words|rupees)\b", re.I)


def _amounts_on_line(label, lines):
    pat = re.compile(label + r"[^\n\d₹]*" + AMOUNT, re.I)
    found = []
    for line in lines:
        if SKIP_LINE.search(line):
            continue
        m = pat.search(line)
        if m:
            # Use the last number on the line: tables often repeat qty/taxable before the total.
            nums = re.findall(r"-?[\d,]+\.\d{1,2}|-?[\d,]{2,}|\b\d\b", line[m.start():])
            v = _num(nums[-1]) if nums else _num(m.group(1))
            if v is not None and v > 0:
                found.append((v, nums))
    return found


def _text_fields(text):
    out = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for label in TOTAL_LABELS:
        found = _amounts_on_line(label, lines)
        if found:
            total, nums = max(found, key=lambda f: f[0])
            out["total"] = total
            # "Total 7604 493.17 8097.17": taxable + tax = total gives us the GST.
            vals = [_num(n) for n in nums]
            if len(vals) >= 3 and None not in vals[-3:] and abs(vals[-3] + vals[-2] - vals[-1]) < 1:
                out["tax"] = vals[-2]
            break
    if "tax" not in out:
        for label in TAX_LABELS:
            found = _amounts_on_line(label, lines)
            if found:
                out["tax"] = found[-1][0]
                break
        else:
            split = [_num(m.group(1)) for ln in lines for m in [re.search(SPLIT_TAX, ln, re.I)] if m]
            split = [v for v in split if v]
            if split:
                out["tax"] = sum(split, ZERO)
    for m in BILL_NO.finditer(text):
        if any(ch.isdigit() for ch in m.group(1)):
            out["bill_number"] = m.group(1).strip("-/")
            break
    m = DATE_LABELLED.search(text)
    d = _date(m.group(1)) if m else None
    if d is None:
        for m in DATE_ANY.finditer(text):
            d = _date(m.group(1))
            if d:
                break
    if d:
        out["bill_date"] = d
    return out


# ------------------------------------------------------------------ main entry


def guess_fields(pages, vendors):
    """Read what we can from a bill.

    `pages` is read_pdf() output (or plain text). Returns a dict with any of:
    vendor, category, bill_number, bill_date, total, tax_amount, lines,
    invoices (list of per-invoice dicts), notes.
    """
    if isinstance(pages, str):
        pages = [{"text": pages, "tables": []}]
    full_text = "\n".join(p["text"] for p in pages)
    out = {}
    if not full_text.strip():
        return out

    lower = full_text.lower()
    for v in vendors:
        if any(k and k in lower for k in v.keywords()):
            out["vendor"] = v
            out["category"] = v.category
            break

    # Split into invoices: a page with a new invoice number starts a new one.
    invoices, current, cols = [], None, None
    for page in pages:
        kv = _key_values(page["tables"])
        text_guess = _text_fields(page["text"])
        number = kv.get("bill_number") or text_guess.get("bill_number")
        if current is None or (number and current["number"] and number != current["number"]):
            current = {"number": number, "date": None, "order_no": None, "lines": [], "total": None, "tax": None,
                       "text": text_guess}
            invoices.append(current)
            cols = None
        current["number"] = current["number"] or number
        current["date"] = current["date"] or _date(kv.get("bill_date")) or text_guess.get("bill_date")
        current["order_no"] = current["order_no"] or kv.get("order_no")
        for table in page["tables"]:
            found_cols, lines, totals = _read_item_table(table)
            if found_cols is None and cols and table and len(table[0]) > max(cols.values()):
                found_cols, lines, totals = _read_item_table(table, cols)  # table continued from last page
            if found_cols:
                cols = found_cols
                current["lines"] += lines
                if totals.get("total"):
                    current["total"], current["tax"] = totals["total"], totals.get("tax")

    for inv in invoices:
        if inv["total"] is None:
            inv["total"] = inv["text"].get("total") or (sum((ln["amount"] for ln in inv["lines"]), ZERO) or None)
        if inv["tax"] is None:
            inv["tax"] = inv["text"].get("tax")
        del inv["text"]
    invoices = [i for i in invoices if i["total"]]
    if not invoices:
        return out

    out["invoices"] = invoices
    out["total"] = sum((i["total"] for i in invoices), ZERO)
    taxes = [i["tax"] for i in invoices if i["tax"] is not None]
    if taxes:
        out["tax_amount"] = sum(taxes, ZERO)
    numbers = [i["number"] for i in invoices if i["number"]]
    if numbers:
        joined = ", ".join(dict.fromkeys(numbers))
        order_no = next((i["order_no"] for i in invoices if i["order_no"]), None)
        out["bill_number"] = joined if len(joined) <= 50 else (order_no or numbers[0])[:50]
    dates = [i["date"] for i in invoices if i["date"]]
    if dates:
        out["bill_date"] = dates[0]
    lines = [ln for i in invoices for ln in i["lines"]]
    if lines:
        out["lines"] = lines
    order_no = next((i["order_no"] for i in invoices if i["order_no"]), None)
    notes = []
    if order_no:
        notes.append(f"Order {order_no}")
    if len(invoices) > 1:
        notes.append(f"{len(invoices)} invoices")
    if notes:
        out["notes"] = " · ".join(notes)
    return out
