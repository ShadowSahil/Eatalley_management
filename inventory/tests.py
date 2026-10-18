from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory.models import Purchase, Vendor
from inventory.pdfparse import guess_fields

SAMPLE_BILL = """
JS FOODS PVT LTD
TAX INVOICE
Invoice No: JSF/2026/0412          Invoice Date: 14-10-2026
Mozzarella Cheese 10 kg  4,200.00
Butter 5 kg 2,350.00
Total Qty 15
Taxable Value 6,550.00
CGST @ 2.5% 163.75
SGST @ 2.5% 163.75
Grand Total ₹ 6,877.50
Rupees Six Thousand Eight Hundred ...
"""


class PdfGuessTests(TestCase):
    def test_reads_common_fields(self):
        found = guess_fields(SAMPLE_BILL, list(Vendor.objects.all()))
        self.assertEqual(found["vendor"].name, "JS Foods")
        self.assertEqual(found["bill_number"], "JSF/2026/0412")
        self.assertEqual(found["bill_date"], date(2026, 10, 14))
        self.assertEqual(found["total"], Decimal("6877.50"))
        self.assertEqual(found["tax_amount"], Decimal("327.50"))

    def test_empty_text(self):
        self.assertEqual(guess_fields("", []), {})


def hyperpure_page(number, kind_rows, total_row):
    """One page as pdfplumber sees a Hyperpure invoice: a header table + item table."""
    table = [
        [f"Invoice Number\n{number}", None, None, "Order No.\nZHPUP27-OR-0000000001", None, None,
         "Invoice Date\n17 Oct 2026", None, None, "Reference PO\n-", None, "Payment Overdue Date\n-",
         None, None, None, None],
        ["Bill From / Shipped From: ZOMATO HYPERPURE PVT LTD - NOIDA"] + [None] * 15,
        ["S No.", "Description of Goods", None, None, None, "HSN", None, "Qty", "Unit Price", None, "UoM", None,
         "Taxable\nAmount", "Tax Rate\n(CGST+SGS\nT+IGST)%", "Tax Amount\n(CGST+SGS\nT+IGST)", "Total"],
        *kind_rows,
        total_row,
        ["Amount Chargeable (in words):", None, None, None, "INR ... Only"] + [None] * 11,
    ]
    return {"text": f"hyperpure\nTAX INVOICE\nInvoice Number Order No. Invoice Date\n{number}", "tables": [table]}


def item(n, desc, qty, unit, taxable, rate, tax, total):
    return [str(n), desc, None, None, None, "0000", None, str(qty), "1", None, unit, None, taxable, rate, tax, total]


class HyperpureTableTests(TestCase):
    def test_two_invoices_in_one_pdf_are_added_up(self):
        pages = [
            hyperpure_page("ZBSUP27-00000001", [
                item(1, "Frozen Sweet Corn, 1 Kg", 2, "Count", "190", "0+0+0", "0+0+0", "190"),
            ], ["", "Total", None, None, None, "", None, "", "", None, "", None, "190", "", "0", "190"]),
            hyperpure_page("ZHPUP27-00000002", [
                item(1, "La Corvinia - Italian Peeled Tomatoes, 2.5\nKg", 6, "Count", "2664", "2.5+2.5+0", "66.6+66.6+0", "2797.20"),
                item(2, "Rajdhani - Maida, 10 Kg", 1, "Bag", "407", "2.5+2.5+0", "10.18+10.18\n+0", "427.35"),
            ], ["", "Total", None, None, None, "", None, "", "", None, "", None, "3071", "", "153.55", "3224.55"]),
        ]
        found = guess_fields(pages, list(Vendor.objects.all()))
        self.assertEqual(found["vendor"].name, "Hyperpure")
        self.assertEqual(found["total"], Decimal("3414.55"))
        self.assertEqual(found["tax_amount"], Decimal("153.55"))
        self.assertEqual(found["bill_number"], "ZBSUP27-00000001, ZHPUP27-00000002")
        self.assertEqual(found["bill_date"], date(2026, 10, 17))
        self.assertIn("2 invoices", found["notes"])
        self.assertEqual(len(found["lines"]), 3)
        self.assertEqual(found["lines"][1]["description"], "La Corvinia - Italian Peeled Tomatoes, 2.5 Kg")
        self.assertEqual((found["lines"][2]["quantity"], found["lines"][2]["unit"]), (Decimal("1"), "Bag"))
        self.assertEqual(sum(ln["amount"] for ln in found["lines"]), found["total"])

    def test_text_layout_with_labels_above_values(self):
        text = "Invoice Number Order No. Invoice Date\nZHPUP27-00216312 ZHPUP27-OR-1 17 Oct 2026\nTotal 7604 493.17 8097.17"
        found = guess_fields(text, [])
        self.assertNotEqual(found.get("bill_number"), "umber")
        self.assertEqual((found["total"], found["tax_amount"]), (Decimal("8097.17"), Decimal("493.17")))


class PurchaseTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("t"))
        self.js = Vendor.objects.get(name="JS Foods")

    def form(self, **extra):
        data = {
            "vendor": self.js.pk, "bill_date": "2026-10-14", "bill_number": "A1", "category": "dairy",
            "total": "", "tax_amount": "0", "payment_mode": "", "notes": "",
            "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            "lines-0-description": "Cheese", "lines-0-quantity": "10", "lines-0-unit": "kg", "lines-0-amount": "4200",
            "lines-1-description": "Butter", "lines-1-quantity": "5", "lines-1-unit": "kg", "lines-1-amount": "2350",
        }
        data.update(extra)
        return self.client.post("/inventory/add/", data)

    def test_total_from_lines_and_duplicate_bill_blocked(self):
        r = self.form()
        self.assertEqual(r.status_code, 302)
        p = Purchase.objects.get()
        self.assertEqual(p.total, Decimal("6550"))
        self.assertEqual(p.lines.count(), 2)
        r = self.form(total="100")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already entered")
        self.assertEqual(Purchase.objects.count(), 1)

    def test_total_required_without_lines(self):
        r = self.form(**{"lines-0-description": "", "lines-0-amount": "", "lines-0-quantity": "", "lines-0-unit": "",
                         "lines-1-description": "", "lines-1-amount": "", "lines-1-quantity": "", "lines-1-unit": ""})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Purchase.objects.count(), 0)

    def test_seeded_vendors(self):
        self.assertEqual(
            sorted(Vendor.objects.values_list("name", flat=True)), ["Hyperpure", "JS Foods", "Naveen Kumar Vegetables", "Sunrise Food Services"]
        )


def make_pdf(lines):
    """A minimal one-page text PDF, enough for pdfplumber to read."""
    text = "BT /F1 11 Tf 40 800 Td 14 TL " + " ".join(
        "(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '" for ln in lines
    ) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010} 00000 n \n" for o in offsets).encode()
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


class ScanFlowTests(TestCase):
    def test_scan_prefills_and_attaches_pdf(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        self.client.force_login(get_user_model().objects.create_user("t"))
        pdf = make_pdf(["Sunrise Flour Mills", "Invoice No: SR-1182", "Date: 12/10/2026", "Maida 50 kg 2,400.00", "Grand Total 2,520.00"])
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            r = self.client.post("/inventory/scan/", {"pdf": SimpleUploadedFile("bill.pdf", pdf, "application/pdf")})
            self.assertContains(r, "Read from the PDF")
            form = r.context["form"]
            self.assertEqual(form.initial["vendor"], Vendor.objects.get(name="Sunrise Food Services").pk)
            self.assertEqual(form.initial["total"], Decimal("2520.00"))
            self.assertEqual(form.initial["bill_number"], "SR-1182")
            token = r.context["pending"]
            r = self.client.post("/inventory/add/", {
                "vendor": form.initial["vendor"], "bill_date": "2026-10-12", "bill_number": "SR-1182", "category": "flour",
                "total": "2520", "tax_amount": "0", "pending": token,
                "lines-TOTAL_FORMS": "0", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
            })
            self.assertEqual(r.status_code, 302)
            p = Purchase.objects.get()
            self.assertRegex(p.bill_file.name, r"inventory/bills/\d{4}/\d{2}/bill(_\w+)?\.pdf$")
            self.assertEqual(self.client.get(p.bill_file.url).status_code, 200)


class NumberParsingTests(TestCase):
    def test_quantities_and_amounts(self):
        from inventory.pdfparse import _num

        self.assertEqual(_num("30.000 kgs"), Decimal("30"))
        self.assertEqual(_num("(cid:299) 13,598.00"), Decimal("13598"))
        self.assertEqual(_num("10.18+10.18\n+0"), Decimal("20.36"))
        self.assertIsNone(_num(""))
        self.assertIsNone(_num("Count"))


class AttachToExistingTests(TestCase):
    """A scanned bill that matches a payment imported from the old sheet is attached, not duplicated."""

    def test_scan_offers_existing_entry_and_attach_fills_it(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        self.client.force_login(get_user_model().objects.create_user("t"))
        sunrise = Vendor.objects.get(name="Sunrise Food Services")
        paid = Purchase.objects.create(vendor=sunrise, bill_date=date(2026, 10, 14), total=Decimal("13598"),
                                       is_paid=True, paid_on=date(2026, 10, 14), notes="Payment recorded in the expense sheet")
        pdf = make_pdf(["SUNRISE FOOD SERVICES", "Invoice No: 26-27/TI-845", "Dated : 13-Oct-26",
                        "IGST OUTPUT 647.50", "Grand Total 13,598.00"])
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            r = self.client.post("/inventory/scan/", {"pdf": SimpleUploadedFile("Sunrise foods.pdf", pdf)})
            self.assertEqual([m.pk for m in r.context["matches"]], [paid.pk])
            self.assertContains(r, "Already recorded?")
            r = self.client.post(f"/inventory/{paid.pk}/attach/", {
                "pending": r.context["pending"], "pending_name": "Sunrise foods.pdf",
            })
            self.assertRedirects(r, f"/inventory/{paid.pk}/edit/")
            paid.refresh_from_db()
            self.assertEqual(Purchase.objects.count(), 1)
            self.assertEqual((paid.bill_number, paid.bill_date, paid.paid_on),
                             ("26-27/TI-845", date(2026, 10, 13), date(2026, 10, 14)))
            self.assertEqual(paid.tax_amount, Decimal("647.50"))
            self.assertTrue(paid.bill_file.name.endswith("Sunrise_foods.pdf"))


class PartOfLumpPaymentTests(TestCase):
    """Old bills paid together in one lump (JS Foods "cheese 15-28 Sept") replace that payment bit by bit."""

    def setUp(self):
        from core.models import Payer

        self.client.force_login(get_user_model().objects.create_user("t"))
        self.js = Vendor.objects.get(name="JS Foods")
        self.partner = Payer.objects.create(name="Partner A")
        self.lump = Purchase.objects.create(
            vendor=self.js, bill_date=date(2026, 10, 12), total=Decimal("24191"), is_paid=True,
            paid_on=date(2026, 10, 12), paid_by=self.partner, notes="Payment recorded in the expense sheet: Cheese bill 15-28 sept",
        )

    def bill(self, number, day, total, part_of=None):
        data = {
            "vendor": self.js.pk, "bill_date": f"2026-09-{day:02d}", "bill_number": number, "category": "dairy",
            "total": str(total), "tax_amount": "0", "payment_mode": "",
            "lines-TOTAL_FORMS": "0", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "1000",
        }
        if part_of:
            data["part_of"] = str(part_of)
        return self.client.post("/inventory/add/", data)

    def test_scan_suggests_the_lump_payment(self):
        from inventory.views import covering_payments

        self.assertEqual(list(covering_payments(self.js, Decimal("10000"), date(2026, 9, 20))), [self.lump])
        self.assertEqual(list(covering_payments(self.js, Decimal("30000"), date(2026, 9, 20))), [])  # bigger than it

    def test_bills_replace_the_lump_without_double_counting(self):
        self.assertEqual(self.bill("JSF/3900", 20, 10000, part_of=self.lump.pk).status_code, 302)
        self.lump.refresh_from_db()
        self.assertEqual(self.lump.total, Decimal("14191"))
        first = Purchase.objects.get(bill_number="JSF/3900")
        self.assertEqual((first.is_paid, first.paid_on, first.paid_by), (True, date(2026, 10, 12), self.partner))
        self.bill("JSF/3950", 27, 14191, part_of=self.lump.pk)
        self.assertFalse(Purchase.objects.filter(pk=self.lump.pk).exists())  # fully replaced by its bills
        self.assertEqual(sum(p.total for p in Purchase.objects.filter(vendor=self.js)), Decimal("24191"))

    def test_scan_page_offers_part_of_payment(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        pdf = make_pdf(["J S FOOD", "Tax Invoice", "Invoice No: JSF/3900", "Dated : 20-Sep-26", "Grand Total 10,000.00"])
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            r = self.client.post("/inventory/scan/", {"pdf": SimpleUploadedFile("js.pdf", pdf)})
        self.assertContains(r, "Part of a bigger payment?")
        self.assertContains(r, f'name="part_of" value="{self.lump.pk}"')

    def test_bill_bigger_than_payment_is_refused(self):
        r = self.bill("JSF/9999", 20, 30000, part_of=self.lump.pk)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "bigger than the")
        self.assertEqual(Purchase.objects.count(), 1)
