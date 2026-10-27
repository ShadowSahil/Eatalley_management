import io
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

import openpyxl
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import SheetImport
from core.sheet_import import SheetError, download, month_tab
from expenses.models import DailyExpense
from fixedcosts.models import FixedCost
from inventory.models import Purchase
from opening.models import OpeningCost
from payroll.models import SalaryPayment

URL = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit#gid=0"
HEADER = ["Date", "Amount", "By", "To", "Type", "Comment", "Mode", "Person", "Total"]


def workbook(october_rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    tabs = {
        "Opening": [[datetime(2026, 5, 5), 50000, "Partner B", "Kitchen shop", "Equipments", "Oven"]],
        "September": [[datetime(2026, 9, 3), 100, "Partner C", "Grocery app", "Inventory", "Milk"]],
        "October": october_rows,
    }
    for name, rows in tabs.items():
        ws = wb.create_sheet(name)
        ws.append(HEADER)
        for r in rows:
            ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


OCTOBER = [
    [datetime(2026, 10, 1), 400, "Eatalley", "Grocery app", "Inventory", "Milk, milkmaid", "", "Eatalley", 1000],
    [datetime(2026, 10, 2), 100, "Eatalley", "Corner shop", "Misc", "Dhoopbatti agarbatti", "Cash"],
    [datetime(2026, 10, 3), 200, "Eatalley", "Ice seller", "Inventory", "Ice", "UPI"],
    [datetime(2026, 10, 1), 1000, "Eatalley", "Hyperpure", "Inventory", "Sauces"],
    [datetime(2026, 10, 5), 1000, "Eatalley", "SFS", "Inventory", "Flour"],
    [datetime(2026, 10, 6), 1000, "Partner A", "J S Foods", "Inventory", "Cheese"],
    [datetime(2026, 10, 7), 1000, "Partner B", "Mokafarms", "Inventory", "Coffee"],
    [datetime(2026, 10, 12), 1000, "Eatalley", "Naveen kumar vegetable", "Inventory", "Veg"],
    [datetime(2026, 10, 10), 5000, "Eatalley", "Landlord", "Rent", "Chef room rent"],
    [datetime(2026, 10, 1), 500, "Eatalley", "Helper", "Salary", "Helper"],
    [datetime(2026, 10, 1), 300, "Eatalley", "Electrician", "Interior", "Fan fitting"],
    ["4-October-2026", "1,200", "Eatalley", "Grocery app", "Inventory", "Paneer milk dahi"],
    [datetime(2026, 9, 30), 99, "Eatalley", "Grocery app", "Inventory", "Milk"],  # typo'd date: not October
    ["soon", 120, "Eatalley", "Grocery app", "Inventory", "Bread"],  # unreadable date
    [None, None, None, None, None, None, None, "Partner A", 1000],  # side summary only
]


class SheetImportTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("owner"))
        patcher = mock.patch("core.sheet_import.download", return_value=workbook(OCTOBER))
        self.download = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, **data):
        return self.client.post("/expenses/import-sheet/", {"url": URL, "month": "2026-10", **data})

    def test_preview_reads_only_october_and_skips_vendors(self):
        r = self.post(action="preview")
        plan = r.context["plan"]
        self.assertEqual(plan["tab"], "October")
        labels = sorted(row["label"] for row in plan["rows"])
        self.assertEqual(labels, [
            "Daily expense · Agarbatti & pest control",
            "Daily expense · Ice",
            "Daily expense · Mixed groceries",
            "Daily expense · Mixed groceries",
            "Fixed cost · Staff room rent",
            "Opening cost · Interior",
            "Salary · Adhoc helper",
        ])
        self.assertEqual(sorted(v["vendor"] for v in plan["vendor_rows"]),
                         ["Hyperpure", "JS Foods", "Mokafarms", "Naveen Kumar Vegetables", "Sunrise Food Services"])
        self.assertEqual([row["row"] for row in plan["other_month"]], [14])
        self.assertEqual(len(plan["problems"]), 1)
        self.assertEqual(plan["total"], Decimal("7700"))
        self.assertFalse(DailyExpense.objects.exists())  # preview saves nothing

    def test_import_and_reimport_replaces(self):
        digest = self.post(action="preview").context["plan"]["digest"]
        r = self.post(action="import", digest=digest)
        self.assertRedirects(r, "/expenses/history/?view=month&d=2026-10-01")
        self.assertEqual(DailyExpense.objects.count(), 4)
        self.assertEqual(FixedCost.objects.get().amount, Decimal("5000"))
        self.assertEqual(SalaryPayment.objects.get().staff.name, "Adhoc helper")
        self.assertEqual(OpeningCost.objects.get().category, "interior")
        self.assertFalse(Purchase.objects.exists())  # vendor rows aren't imported at all
        ice = DailyExpense.objects.get(item__name="Ice")
        self.assertEqual((ice.payment_mode, ice.paid_by.name, ice.source), ("upi", "Eatalley", "gsheet:2026-10"))
        self.assertEqual(DailyExpense.objects.get(amount=Decimal("1200")).date, date(2026, 10, 4))

        self.post(action="import", digest=digest)  # again: replaced, not doubled
        self.assertEqual(DailyExpense.objects.count(), 4)
        self.assertEqual(SalaryPayment.objects.count(), 1)
        self.assertEqual(SheetImport.objects.count(), 2)
        r = self.client.get("/expenses/import-sheet/")
        self.assertEqual(r.context["url"], URL)  # link remembered

    def test_sheet_changed_since_preview(self):
        self.post(action="import", digest="stale")
        self.assertFalse(DailyExpense.objects.exists())

    def test_missing_month_tab(self):
        r = self.client.post("/expenses/import-sheet/", {"url": URL, "month": "2026-08", "action": "preview"})
        self.assertIn("no 'August' tab", r.context["error"])


class SheetHelpersTests(TestCase):
    def test_month_tab_names(self):
        oct26 = date(2026, 10, 1)
        self.assertEqual(month_tab(["Opening", "September", "October"], oct26), "October")
        self.assertEqual(month_tab(["Oct 2026", "Sep 2026"], oct26), "Oct 2026")
        self.assertEqual(month_tab(["october-26"], oct26), "october-26")
        with self.assertRaises(SheetError):
            month_tab(["Opening", "Oct 2025"], oct26)

    def test_private_sheet_gives_a_clear_error(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"<!doctype html><title>Sign in</title>"
        with mock.patch("urllib.request.urlopen", return_value=resp), self.assertRaises(SheetError) as e:
            download(URL)
        self.assertIn("Anyone with the link", str(e.exception))
        with self.assertRaises(SheetError):
            download("https://example.com/not-a-sheet")
