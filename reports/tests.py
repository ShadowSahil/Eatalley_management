from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.periods import get_period
from expenses.models import DailyExpense, ExpenseItem
from inventory.models import Purchase, Vendor
from payroll.models import SalaryPayment, Staff
from reports.services import pnl
from sales.models import SaleItemLine, SaleOrder


class PnlTests(TestCase):
    def setUp(self):
        d = date(2026, 9, 10)
        SaleOrder.objects.create(invoice_no="1", date=d, total=Decimal("10500"), tax=Decimal("500"))
        SaleOrder.objects.create(invoice_no="2", date=d, total=Decimal("999"), tax=Decimal("49"), is_cancelled=True)
        # Item report for a day that has no orders report -> used as fallback.
        SaleItemLine.objects.create(date=date(2026, 9, 11), item_name="Pizza", quantity=10, amount=Decimal("3000"))
        # Item report for a day that also has orders -> ignored for revenue.
        SaleItemLine.objects.create(date=d, item_name="Pizza", quantity=10, amount=Decimal("9999"))
        Purchase.objects.create(vendor=Vendor.objects.get(name="Sunrise Food Services"), bill_date=d, total=Decimal("2000"))
        DailyExpense.objects.create(date=d, item=ExpenseItem.objects.get(name="Milk"), amount=Decimal("500"))
        s = Staff.objects.create(name="Chef", monthly_salary=30000)
        SalaryPayment.objects.create(staff=s, month=d, amount=30000)

    def test_month(self):
        p = pnl(get_period({"view": "month", "d": "2026-09-01"}))
        self.assertEqual(p["revenue"], Decimal("13000"))
        self.assertEqual(p["inventory"], Decimal("2000"))
        self.assertEqual(p["expenses"], Decimal("500"))
        self.assertEqual(p["salary"], Decimal("30000"))
        self.assertEqual(p["profit"], Decimal("13000") - Decimal("32500"))
        self.assertEqual(p["food_cost"], Decimal("2500"))  # flour bill + milk
        self.assertEqual(sum(r["revenue"] for r in p["rows"]), p["revenue"])
        self.assertAlmostEqual(float(sum(r["salary"] for r in p["rows"])), 30000, places=2)

    def test_fy_buckets_are_months(self):
        p = pnl(get_period({"view": "fy", "d": "2026-09-01"}))
        self.assertEqual(len(p["rows"]), 12)
        self.assertEqual(p["rows"][5]["revenue"], Decimal("13000"))  # September


class SmokeTests(TestCase):
    """Every page renders for a logged-in team member, with and without data."""

    def test_pages(self):
        self.client.force_login(get_user_model().objects.create_user("t", first_name="Test"))
        PnlTests.setUp(self)
        urls = [
            "/expenses/", "/expenses/?date=2026-09-10", "/expenses/history/", "/expenses/items/",
            "/sales/", "/sales/upload/", "/inventory/", "/inventory/add/", "/inventory/vendors/",
            "/staff/", "/staff/pay/", "/staff/add/", "/team/", "/password/",
            "/opening/", "/opening/?category=equipment&q=oven", "/pnl/paid-by/", "/pnl/paid-by/?start=2026-09-01",
        ]
        for kind in ["day", "week", "month", "quarter", "fy", "custom"]:
            for base in ["/sales/", "/pnl/", "/inventory/", "/expenses/history/"]:
                urls.append(f"{base}?view={kind}&d=2026-09-10&start=2026-08-01&end=2026-09-30")
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get("/pnl/?view=fy&d=2026-09-10&format=csv")["Content-Type"], "text/csv")


class PaidByAndOpeningTests(TestCase):
    def test_opening_costs_and_gst_payments_stay_out_of_pnl(self):
        from core.models import Payer
        from opening.models import OpeningCost

        partner = Payer.objects.create(name="Partner A")
        d = date(2026, 9, 10)
        OpeningCost.objects.create(date=d, amount=50000, category="equipment", paid_by=partner)
        gst = ExpenseItem.objects.create(name="GST payment", category="gst")
        DailyExpense.objects.create(date=d, item=gst, amount=3630)
        DailyExpense.objects.create(date=d, item=ExpenseItem.objects.get(name="Milk"), amount=100, paid_by=partner)
        p = pnl(get_period({"view": "month", "d": "2026-09-01"}))
        self.assertEqual(p["expenses"], Decimal("100"))
        self.assertEqual(p["gst_paid"], Decimal("3630"))
        self.assertEqual(p["total_cost"], Decimal("100"))

        self.client.force_login(get_user_model().objects.create_user("t"))
        r = self.client.get("/pnl/paid-by/")
        partner_row = next(row for row in r.context["table"] if row["name"] == "Partner A")
        self.assertEqual(partner_row["total"], Decimal("50100"))
        r = self.client.get("/opening/")
        self.assertEqual(r.context["total"], Decimal("50000"))

    def test_expense_entry_defaults_to_business_payer(self):
        self.client.force_login(get_user_model().objects.create_user("t"))
        milk = ExpenseItem.objects.get(name="Milk")
        self.client.post("/expenses/", {"date": "2026-09-10", "item": [str(milk.pk)], "amount": ["60"], "mode": ["upi"]})
        self.assertEqual(DailyExpense.objects.get().paid_by.name, "Eatalley")
