from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.periods import get_period
from fixedcosts.models import FixedCost, FixedCostHead
from reports.services import pnl


class FixedCostTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("t"))
        self.rent = FixedCostHead.objects.get(name="Rent")

    def test_seeded_types(self):
        self.assertEqual(sorted(FixedCostHead.objects.values_list("name", flat=True)),
                         ["Electricity bill", "Rent", "Staff room rent"])

    def test_add_for_a_month_and_prefill_last_amount(self):
        r = self.client.post("/fixed/add/", {
            "head": self.rent.pk, "month": "2026-09", "amount": "31000", "paid_on": "2026-10-03", "payment_mode": "bank",
        })
        self.assertRedirects(r, "/fixed/?month=2026-09")
        c = FixedCost.objects.get()
        self.assertEqual((c.month, c.paid_on, c.amount), (date(2026, 9, 1), date(2026, 10, 3), Decimal("31000")))
        # next month's "Add" pre-fills the same amount; the month page shows what's missing
        r = self.client.get(f"/fixed/add/?month=2026-10&head={self.rent.pk}")
        self.assertEqual(r.context["form"].initial["amount"], Decimal("31000"))
        r = self.client.get("/fixed/?month=2026-09")
        self.assertEqual([h.name for h in r.context["missing"]], ["Electricity bill", "Staff room rent"])

    def test_add_type(self):
        self.client.post("/fixed/types/add/", {"head-name": "Internet", "head-is_active": "on"})
        self.assertTrue(FixedCostHead.objects.filter(name="Internet").exists())
        r = self.client.post("/fixed/types/add/", {"head-name": "rent", "head-is_active": "on"})
        self.assertContains(r, "already exists")

    def test_counts_in_pnl_for_its_month(self):
        FixedCost.objects.create(head=self.rent, month=date(2026, 10, 1), amount=Decimal("31000"), paid_on=date(2026, 11, 2))
        month = pnl(get_period({"view": "month", "d": "2026-10-15"}))
        self.assertEqual(month["fixed"], Decimal("31000"))
        self.assertEqual(month["fixed_by_head"], [{"name": "Rent", "amount": Decimal("31000")}])
        self.assertEqual(sum(r["fixed"] for r in month["rows"]), Decimal("31000"))
        day = pnl(get_period({"view": "day", "d": "2026-10-15"}))
        self.assertEqual(day["fixed"], Decimal("1000"))  # 1/31 of October
        self.assertEqual(pnl(get_period({"view": "month", "d": "2026-11-15"}))["fixed"], Decimal("0"))
