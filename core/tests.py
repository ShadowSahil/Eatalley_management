from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.periods import get_period
from core.templatetags.money import format_inr


class PeriodTests(TestCase):
    def test_financial_year_runs_april_to_march(self):
        p = get_period({"view": "fy", "d": "2026-02-10"})
        self.assertEqual((p.start, p.end), (date(2025, 4, 1), date(2026, 3, 31)))
        self.assertEqual(len(p.buckets), 12)
        self.assertIn("FY 2025-26", p.label)

    def test_quarters_are_financial_quarters(self):
        p = get_period({"view": "quarter", "d": "2026-10-18"})
        self.assertEqual((p.start, p.end), (date(2026, 10, 1), date(2026, 12, 31)))
        self.assertTrue(p.label.startswith("Q3"))
        p = get_period({"view": "quarter", "d": "2027-01-05"})
        self.assertEqual((p.start, p.end), (date(2027, 1, 1), date(2027, 3, 31)))
        self.assertTrue(p.label.startswith("Q4 FY 2026-27"))

    def test_week_starts_monday(self):
        p = get_period({"view": "week", "d": "2026-10-18"})  # a Sunday
        self.assertEqual((p.start, p.end), (date(2026, 10, 12), date(2026, 10, 18)))
        self.assertEqual(p.next_anchor, date(2026, 10, 19))

    def test_month_and_bad_input(self):
        p = get_period({"view": "month", "d": "2026-02-14"})
        self.assertEqual((p.start, p.end, p.days), (date(2026, 2, 1), date(2026, 2, 28), 28))
        p = get_period({"view": "nonsense", "d": "not-a-date"})
        self.assertEqual(p.kind, "month")

    def test_custom_range_swaps_reversed_dates(self):
        p = get_period({"view": "custom", "start": "2026-10-10", "end": "2026-10-01"})
        self.assertEqual((p.start, p.end), (date(2026, 10, 1), date(2026, 10, 10)))


class MoneyTests(TestCase):
    def test_indian_grouping(self):
        self.assertEqual(format_inr(1234567), "₹12,34,567")
        self.assertEqual(format_inr("999.5", 2), "₹999.50")
        self.assertEqual(format_inr(-150000), "-₹1,50,000")
        self.assertEqual(format_inr(None), "₹0")


class LoginTests(TestCase):
    def test_pages_need_login(self):
        r = self.client.get("/sales/")
        self.assertRedirects(r, "/login/?next=/sales/")

    def test_team_member_gets_full_access(self):
        admin = get_user_model().objects.create_user("owner", password="x" * 10)
        self.client.force_login(admin)
        r = self.client.post("/team/", {"first_name": "Rahul", "username": "Rahul", "password": "pizza-oven-42"})
        self.assertRedirects(r, "/team/")
        u = get_user_model().objects.get(username="rahul")
        self.assertTrue(u.is_superuser and u.check_password("pizza-oven-42"))
