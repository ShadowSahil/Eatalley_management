import io
from datetime import date, datetime
from decimal import Decimal

import openpyxl
from django.core.management import call_command
from django.test import TestCase

from core.models import Payer
from expenses.models import DailyExpense
from inventory.models import Purchase
from opening.models import OpeningCost
from payroll.models import SalaryPayment, Staff

HEADER = ["Date", "Amount", "By", "To", "Type", "Comment", "Mode", "Person", "Total"]


def sheet(path):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    tabs = {
        "Opening": [
            [datetime(2026, 5, 5), 80000, "Partner B", "Kitchen Equipments", "Equipments", "Oven"],
            [datetime(2026, 8, 20), 50000, "Partner C", "QBIT", "Equipments", "Computer + Printer"],
        ],
        "August": [
            [datetime(2026, 8, 21), 22655, "Partner B", "J S Foods", "Inventory", "Cheese bufallo"],
            [datetime(2026, 8, 26), 414, "Partner B", "Blinkit", "Misc", "Hit/agarbatti"],
            [datetime(2026, 8, 31), 21000, "Partner D", "Ravi", "Salary", "Ravi Kumar"],
            [datetime(2026, 8, 31), 24294, "Partner C", "Electricity", "Bill", "Electricity + Maintenance"],
        ],
        "September": [
            [datetime(2026, 9, 1), 5000, "Eatalley", "Ravi", "Salary", "Ravi Kumar"],
            [datetime(2026, 9, 5), 300, "Eatalley", "Zepto", "Inventory", "Milk", "Cash"],
            [datetime(2026, 9, 6), 900, "Eatalley", "BigBasket", "Inventory", "Milk, paneer, milkmaid, rice"],
            [datetime(2026, 9, 7), 500, "Eatalley", "Labour", "Salary", "Labour"],
            [datetime(2026, 9, 11), 4000, "Partner A", "Qbit", "Equipments", "Cash drawer"],
            [datetime(2026, 9, 20), 3630, "Eatalley", "GST", "Misc", "GST Filing"],
        ],
        "October": [
            [datetime(2026, 10, 1), 35000, "Eatalley", "Ravi", "Salary", "Ravi Kumar"],
            [datetime(2026, 10, 1), 10000, "Eatalley", "Ravi", "Salary", "Advance salary"],
            [datetime(2026, 10, 2), 2400, "Eatalley", "Amar Gas", "Inventory", "Cylinder"],
            [datetime(2026, 10, 12), 16480, "Eatalley", "Naveen kumar vegetable", "Inventory", datetime(2026, 1, 11)],
        ],
    }
    for name, rows in tabs.items():
        ws = wb.create_sheet(name)
        ws.append(HEADER)
        for r in rows:
            ws.append(r)
    wb.save(path)


class ImportSheetTests(TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.NamedTemporaryFile(suffix=".xlsx")
        sheet(self.tmp.name)

    def run_cmd(self, *args):
        out = io.StringIO()
        call_command("import_expense_sheet", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_saves_nothing(self):
        out = self.run_cmd(self.tmp.name, "--dry-run")
        self.assertIn("Dry run", out)
        self.assertFalse(DailyExpense.objects.exists())

    def test_rows_go_to_the_right_place(self):
        Staff.objects.create(name="Ravi Kumar", role="Chef", monthly_salary=40000)
        self.run_cmd(self.tmp.name)
        # vendor bills
        self.assertEqual(Purchase.objects.count(), 2)
        js = Purchase.objects.get(vendor__name="JS Foods")
        self.assertEqual((js.total, js.paid_by.name, js.is_paid), (Decimal("22655"), "Partner B", True))
        self.assertEqual(Purchase.objects.get(vendor__name="Naveen Kumar Vegetables").notes,
                         "Payment recorded in the expense sheet")  # date-mangled comment dropped
        # daily expenses and their items
        items = dict(DailyExpense.objects.values_list("item__name", "amount"))
        self.assertEqual(items["Milk"], Decimal("300"))
        self.assertEqual(items["Mixed groceries"], Decimal("900"))
        self.assertEqual(items["Gas Cylinder"], Decimal("2400"))
        self.assertEqual(items["Agarbatti & pest control"], Decimal("414"))
        self.assertEqual(items["GST payment"], Decimal("3630"))
        self.assertEqual(DailyExpense.objects.get(item__name="Milk").payment_mode, "cash")
        # salaries: the monthly chef, labour is adhoc
        chef = Staff.objects.get(name="Ravi Kumar")
        self.assertEqual(chef.monthly_salary, Decimal("40000"))
        months = sorted((p.month, p.kind, p.amount) for p in chef.payments.all())
        self.assertEqual(months, [
            (date(2026, 8, 1), "salary", Decimal("21000")),
            (date(2026, 9, 1), "salary", Decimal("5000")),
            (date(2026, 9, 1), "salary", Decimal("35000")),   # paid 1 Oct, counts for September
            (date(2026, 10, 1), "advance", Decimal("10000")),
        ])
        self.assertEqual(SalaryPayment.objects.get(staff__name="Adhoc helper").amount, Decimal("500"))
        # one-time costs: Opening tab + equipment from the month tabs
        self.assertEqual(OpeningCost.objects.count(), 3)
        self.assertEqual(OpeningCost.objects.get(description="Cash drawer").category, "equipment")
        # people
        self.assertTrue(Payer.objects.get(name="Eatalley").is_business)
        self.assertEqual(Payer.objects.filter(is_business=False).count(), 4)

    def test_cannot_import_twice_and_undo_removes_everything(self):
        self.run_cmd(self.tmp.name)
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_cmd(self.tmp.name)
        self.run_cmd("--undo")
        for m in (DailyExpense, Purchase, SalaryPayment, OpeningCost):
            self.assertFalse(m.objects.exists(), m.__name__)
