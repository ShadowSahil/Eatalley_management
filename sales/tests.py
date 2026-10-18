import io
from datetime import date, datetime
from decimal import Decimal

import openpyxl
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from core.periods import get_period
from sales.importer import SalesImportError, import_file
from sales.models import SaleItemLine, SaleOrder, SalePayment, SalesUpload
from sales.services import sales_summary


def xlsx(rows, name="orders.xlsx"):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(name, buf.getvalue())


ORDERS = [
    ["Eatalley"],
    ["Order Summary Report"],
    ["Date: 16 Oct 2026 to 17 Oct 2026"],
    [],
    ["Invoice No.", "Date", "Order Type", "Payment Type", "Status", "My Amount (₹)", "Discount (₹)",
     "CGST (₹)", "SGST (₹)", "Delivery Charge", "Container Charge", "Grand Total (₹)"],
    [101, datetime(2026, 10, 16, 20, 15), "Dine In", "Cash", "Success", 500, 50, 11.25, 11.25, 0, 0, 472.5],
    [102, datetime(2026, 10, 16, 21, 0), "Delivery", "Other [UPI]", "Success", 800, 0, 20, 20, 30, 10, 880],
    [103, "17-10-2026 13:05", "Pick Up", "Card", "Cancelled", 300, 0, 7.5, 7.5, 0, 0, 315],
    [104, "17/10/2026", "Dine In", "Cash", "Success", "1,000", "100", "22.50", "22.50", 0, 0, "945"],
    ["Total", None, None, None, None, 2600, 150, 61.25, 61.25, 30, 10, 2612.5],
]


# Layout of Petpooja's "Order Report" export (Order_Listing_*.xlsx), with
# made-up customers. Part payments: Grand Total is 0 on the bill's row, the
# real total is in Payment Description, and one row per payment follows.
PETPOOJA_HEADER = [
    "Order No.", "Client OrderID", "Order Type", "Sub Order Type", "Customer Name", "Customer Phone", "GSTIN",
    "Customer Address", "Delivery Boy", "Delivery Boy Number", "Items", "My Amount (₹)", "Total Discount (₹)",
    "Delivery Charge (₹)", "Container Charge (₹)", "Total Tax (₹)", "Round Off (₹)", "Grand Total (₹)",
    "Payment Type", "Payment Description", "Status", "Created", "Sequence Name",
]


def pp_row(no, typ, items, amt, disc, tax, rnd, total, pay, status, created, desc=None):
    return [no, None, typ, "Fine Dine", None, None, None, None, None, None, items, amt, disc, 0.0, 0.0,
            tax, rnd, total, pay, desc, status, created, None]


def pp_split(no, amount, mode):
    return [no] + [None] * 16 + [amount, mode] + [None] * 4


PETPOOJA = [
    ["Name:", "Order Report"],
    ["Restaurant Name:", "Eatalley"],
    ["Restaurant Address:", "Knowledge Park 2"],
    [],
    PETPOOJA_HEADER,
    pp_row(1186, "Dine In (T1)", "Margherita Pizza", 395.0, 0.0, 19.76, 0.24, 415.0, "UPI", "Printed", "18 Oct 2026 18:05:04"),
    pp_row(1184, "Dine In (T3)", "Mushroom Sandwich, Paneer Bowl", 1335.0, 267.0, 53.4, -0.4, 1121.0, "UPI", "Printed", "18 Oct 2026 16:49:49"),
    pp_row(1166, "Dine In (T2)", "Pesto Pizza", 1025.0, 0.0, 51.26, -0.26, 0.0, "Part Payment", "Printed",
           "17 Oct 2026 18:40:33", "Total : 1076.00"),
    pp_split(1166, 76, "UPI"),
    pp_split(1166, 1000, "Cash"),
    pp_split(1166, 0, "Not Paid"),
    pp_row(1156, "Dine In (T1)", "Garden Veggie Pizza", 875.0, 0.0, 43.76, 0.24, 919.0, "UPI", "Cancelled", "17 Oct 2026 15:34:47"),
    pp_row(1150, "Dine In (T4)", "Chicken Trio", 1150.0, 0.0, 57.5, 0.5, 1200.0, "Card", "Printed", "17 Oct 2026 12:32:16"),
]


class PetpoojaOrderReportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("t")
        self.up = import_file(xlsx(PETPOOJA, "Order_Listing.xlsx"), self.user)

    def test_reads_orders_dates_and_order_type(self):
        self.assertEqual(self.up.report_type, "orders")
        self.assertEqual(SaleOrder.objects.count(), 5)
        o = SaleOrder.objects.get(invoice_no="1186")
        self.assertEqual((o.date, o.time.hour, o.order_type, o.source), (date(2026, 10, 18), 18, "Dine In", "Fine Dine"))
        self.assertTrue(SaleOrder.objects.get(invoice_no="1156").is_cancelled)

    def test_part_payment_total_and_split(self):
        o = SaleOrder.objects.get(invoice_no="1166")
        self.assertEqual(o.total, Decimal("1076.00"))
        self.assertEqual(
            sorted((p.mode, p.amount) for p in o.payments.all()), [("Cash", Decimal("1000")), ("UPI", Decimal("76"))]
        )

    def test_summary_by_payment_mode(self):
        s = sales_summary(get_period({"view": "week", "d": "2026-10-17"}))
        self.assertEqual(s["orders"], 4)
        self.assertEqual(s["total"], Decimal("3812"))
        modes = {r["name"]: (r["orders"], r["amount"]) for r in s["by_payment"]}
        self.assertEqual(modes, {
            "UPI": (3, Decimal("1612")), "Card": (1, Decimal("1200")), "Cash": (1, Decimal("1000")),
        })
        # round-offs (+0.24 -0.40 -0.26) plus bill 1150 settled at ₹1,200 against ₹1,207.50
        self.assertEqual(s["adjustment"], Decimal("-7.92"))


class ImporterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("t")

    def test_orders_report_with_title_rows_and_total_row(self):
        up = import_file(xlsx(ORDERS), self.user)
        self.assertEqual(up.report_type, "orders")
        self.assertEqual(up.rows_imported, 4)
        self.assertEqual((up.start_date, up.end_date), (date(2026, 10, 16), date(2026, 10, 17)))
        o = SaleOrder.objects.get(invoice_no="102")
        self.assertEqual(o.payment_mode, "Other [UPI]")
        self.assertEqual(o.tax, Decimal("40"))  # CGST + SGST summed
        self.assertEqual(o.delivery_charge, Decimal("30"))
        self.assertTrue(SaleOrder.objects.get(invoice_no="103").is_cancelled)
        self.assertEqual(SaleOrder.objects.get(invoice_no="104").gross_amount, Decimal("1000"))

    def test_reupload_replaces_same_dates(self):
        import_file(xlsx(ORDERS), self.user)
        import_file(xlsx(ORDERS), self.user)
        self.assertEqual(SaleOrder.objects.count(), 4)
        self.assertEqual(SalesUpload.objects.count(), 1)  # the fully replaced upload is cleaned up

    def test_summary_excludes_cancelled(self):
        import_file(xlsx(ORDERS), self.user)
        s = sales_summary(get_period({"view": "month", "d": "2026-10-01"}))
        self.assertEqual(s["orders"], 3)
        self.assertEqual(s["total"], Decimal("2297.5"))
        self.assertEqual(s["net_revenue"], Decimal("2297.5") - Decimal("107.5"))
        self.assertEqual(s["discount"], Decimal("150"))
        self.assertEqual(s["cancelled_count"], 1)
        modes = {r["name"]: r["amount"] for r in s["by_payment"]}
        self.assertEqual(modes["Cash"], Decimal("1417.5"))

    def test_item_report_csv_needs_date(self):
        csv = b"Item Wise Report\nCategory,Item,Qty,Amount\nPizza,Margherita,12,\"3,588.00\"\nBeverages,Coke,5,300\nTotal,,17,3888\n"
        with self.assertRaises(SalesImportError):
            import_file(SimpleUploadedFile("items.csv", csv), self.user)
        up = import_file(SimpleUploadedFile("items.csv", csv), self.user, fallback_date=date(2026, 10, 17))
        self.assertEqual(up.report_type, "items")
        self.assertEqual(SaleItemLine.objects.count(), 2)
        self.assertEqual(SaleItemLine.objects.get(item_name="Margherita").amount, Decimal("3588.00"))

    def test_rejects_unrelated_file(self):
        with self.assertRaises(SalesImportError):
            import_file(xlsx([["foo", "bar"], [1, 2]]), self.user)

    def test_upload_page(self):
        self.client.force_login(self.user)
        r = self.client.post("/sales/upload/", {"file": xlsx(ORDERS)})
        self.assertEqual(r.status_code, 302)
        r = self.client.get(r["Location"])
        self.assertContains(r, "₹2,298")  # total sales tile (rounded)
