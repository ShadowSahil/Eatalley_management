from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from payroll.models import Leave, SalaryPayment, Staff
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
        self.assertEqual(c["total"], Decimal("48000"))  # chef only: Sep 30000 + 18/30 of Oct

    def test_advance_alone_does_not_settle_the_month(self):
        SalaryPayment.objects.create(staff=self.b, month=date(2026, 10, 1), kind="advance", amount=3000)
        c = salary_cost(date(2026, 10, 1), date(2026, 10, 31), as_of=date(2026, 10, 31))
        self.assertEqual(c["actual"], Decimal("3000"))
        self.assertEqual(c["total"], Decimal("42000"))  # chef 30000 + helper 12000

    def test_current_month_only_counts_days_worked(self):
        SalaryPayment.objects.create(staff=self.b, month=date(2026, 10, 1), kind="advance", amount=3000)
        c = salary_cost(date(2026, 10, 1), date(2026, 10, 31), as_of=date(2026, 10, 18))
        # chef 30000 x 18/30 = 18000; helper 12000 x 18/30 = 7200, of which 3000 already paid
        self.assertEqual(c["actual"], Decimal("3000"))
        self.assertEqual(c["total"], Decimal("25200"))

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


class LeaveTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("owner"))
        self.chef = Staff.objects.create(name="Chef A", monthly_salary=Decimal("20000"), leave_allowance=Decimal("2"))

    def record(self, **data):
        return self.client.post("/staff/leave/", {"staff": self.chef.pk, "kind": "leave", **data})

    def test_record_and_count_against_allowance(self):
        self.assertRedirects(self.record(start="2026-10-05"), "/staff/?month=2026-10")  # 'To' defaults to 'From'
        self.record(start="2026-10-12", half_day="on")
        self.record(start="2026-10-30", end="2026-11-02")  # crosses the month end: 2 days in Oct, 2 in Nov
        r = self.client.get("/staff/?month=2026-10")
        row = next(x for x in r.context["rows"] if x["staff"] == self.chef)
        self.assertEqual((row["leave_days"], row["over_allowance"]), (Decimal("3.5"), Decimal("1.5")))
        self.assertEqual(len(r.context["leaves"]), 3)
        r = self.client.get("/staff/?month=2026-11")
        self.assertEqual(next(x for x in r.context["rows"] if x["staff"] == self.chef)["leave_days"], Decimal("2"))
        # tracking only: the balance still owes the full salary
        self.assertEqual(row["balance"], Decimal("20000"))

    def test_bad_leaves_are_refused(self):
        self.record(start="2026-10-05", end="2026-10-06")
        r = self.record(start="2026-10-06")
        self.assertContains(r, "already has leave recorded")
        r = self.record(start="2026-10-10", end="2026-10-09")
        self.assertContains(r, "can&#x27;t be before")
        r = self.record(start="2026-10-10", end="2026-10-11", half_day="on")
        self.assertContains(r, "A half day is a single day")
        self.assertEqual(Leave.objects.count(), 1)

    def test_edit_delete_and_staff_page(self):
        self.record(start="2026-10-05")
        lv = Leave.objects.get()
        self.client.post(f"/staff/leave/{lv.pk}/edit/", {"staff": self.chef.pk, "kind": "sick", "start": "2026-10-05",
                                                         "end": "2026-10-07"})
        lv.refresh_from_db()
        self.assertEqual((lv.kind, lv.days), ("sick", 3))
        r = self.client.get(f"/staff/{self.chef.pk}/edit/")
        self.assertContains(r, "Leave history")
        self.client.post(f"/staff/leave/{lv.pk}/delete/")
        self.assertFalse(Leave.objects.exists())


class ProRataTests(TestCase):
    """A joining or leaving month is paid for the days worked, out of a fixed 30-day month."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("owner"))
        self.new = Staff.objects.create(name="New Cook", monthly_salary=16000, joined_on=date(2026, 10, 16))

    def test_days_worked(self):
        s = self.new
        self.assertEqual((s.days_worked(date(2026, 10, 1)), s.salary_for(date(2026, 10, 1))), (15, Decimal("8000")))
        self.assertEqual((s.days_worked(date(2026, 11, 1)), s.salary_for(date(2026, 11, 1))), (30, Decimal("16000")))
        self.assertEqual(s.days_worked(date(2026, 9, 1)), 0)  # before joining
        self.assertEqual(s.days_worked(date(2026, 10, 1), until=date(2026, 10, 20)), 5)
        s.joined_on = date(2026, 10, 31)
        self.assertEqual(s.days_worked(date(2026, 10, 1)), 1)  # the 31st counts as the 30th
        s.joined_on = date(2027, 2, 16)
        self.assertEqual(s.days_worked(date(2027, 2, 1)), 15)  # end of February counts as the 30th
        s.joined_on, s.left_on = date(2026, 1, 1), date(2026, 12, 10)
        self.assertEqual((s.days_worked(date(2026, 12, 1)), s.salary_for(date(2026, 12, 1))), (10, Decimal("5333")))

    def test_staff_page_and_pay_all_use_the_pro_rated_salary(self):
        SalaryPayment.objects.create(staff=self.new, month=date(2026, 10, 1), kind="advance", amount=2000)
        r = self.client.get("/staff/?month=2026-10")
        row = next(x for x in r.context["rows"] if x["staff"] == self.new)
        self.assertEqual((row["due"], row["days"], row["balance"]), (Decimal("8000"), 15, Decimal("6000")))
        self.assertContains(r, "15 of 30 days")
        self.client.post("/staff/pay/all/", {"month": "2026-10-01"})
        self.assertEqual(SalaryPayment.objects.get(kind="salary").amount, Decimal("6000"))

    def test_pnl_estimate_starts_from_joining(self):
        c = salary_cost(date(2026, 10, 1), date(2026, 10, 31), as_of=date(2026, 11, 5))
        self.assertEqual(c["total"], Decimal("8000"))
