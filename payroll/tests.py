from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from payroll.models import SalaryPayment, Staff
from payroll.services import salary_cost


class SalaryCostTests(TestCase):
    def setUp(self):
        self.a = Staff.objects.create(name="Chef", monthly_salary=30000, joined_on=date(2026, 1, 1))
        self.b = Staff.objects.create(name="Helper", monthly_salary=12000, joined_on=date(2026, 1, 1))

    def test_actual_payments_used_and_unpaid_staff_estimated(self):
        SalaryPayment.objects.create(staff=self.a, month=date(2026, 9, 15), amount=29000)
        c = salary_cost(date(2026, 9, 1), date(2026, 9, 30), as_of=date(2026, 10, 18))
        self.assertEqual(c["actual"], Decimal("29000"))
        self.assertEqual(c["estimated"], Decimal("12000"))
        self.assertEqual(c["total"], Decimal("41000"))

    def test_single_day_gets_share_of_month(self):
        SalaryPayment.objects.create(staff=self.a, month=date(2026, 9, 1), amount=30000)
        SalaryPayment.objects.create(staff=self.b, month=date(2026, 9, 1), amount=12000)
        c = salary_cost(date(2026, 9, 10), date(2026, 9, 10), as_of=date(2026, 10, 18))
        self.assertEqual(c["total"], Decimal("1400"))

    def test_future_months_and_left_staff_not_estimated(self):
        self.b.left_on = date(2026, 8, 31)
        self.b.save()
        c = salary_cost(date(2026, 9, 1), date(2026, 12, 31), as_of=date(2026, 10, 18))
        self.assertEqual(c["total"], Decimal("47419.35"))  # chef only: Sep 30000 + 18/31 of Oct

    def test_advance_alone_does_not_settle_the_month(self):
        SalaryPayment.objects.create(staff=self.b, month=date(2026, 10, 1), kind="advance", amount=3000)
        c = salary_cost(date(2026, 10, 1), date(2026, 10, 31), as_of=date(2026, 10, 31))
        self.assertEqual(c["actual"], Decimal("3000"))
        self.assertEqual(c["total"], Decimal("42000"))  # chef 30000 + helper 12000

    def test_current_month_only_counts_days_worked(self):
        SalaryPayment.objects.create(staff=self.b, month=date(2026, 10, 1), kind="advance", amount=3000)
        c = salary_cost(date(2026, 10, 1), date(2026, 10, 31), as_of=date(2026, 10, 18))
        # chef 30000 x 18/31 = 17419.35; helper 12000 x 18/31 = 6967.74, of which 3000 already paid
        self.assertEqual(c["actual"], Decimal("3000"))
        self.assertEqual(c["total"], Decimal("24387.10"))

    def test_no_estimates_before_tracking_started(self):
        c = salary_cost(date(2026, 4, 1), date(2026, 9, 30), as_of=date(2026, 10, 18), estimate_from=date(2026, 8, 20))
        self.assertEqual(c["total"], Decimal("84000"))  # Aug + Sep only


class PayAllTests(TestCase):
    def test_pays_remaining_balance_after_advance(self):
        self.client.force_login(get_user_model().objects.create_user("t"))
        s = Staff.objects.create(name="Chef", monthly_salary=30000)
        SalaryPayment.objects.create(staff=s, month=date(2026, 10, 1), kind="advance", amount=5000)
        self.client.post("/staff/pay/all/", {"month": "2026-10-01"})
        self.assertEqual(
            SalaryPayment.objects.get(kind="salary").amount, Decimal("25000")
        )
