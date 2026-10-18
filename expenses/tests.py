from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from core.periods import today
from expenses.models import DailyExpense, ExpenseItem


class EntryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("t")
        self.client.force_login(self.user)
        self.milk = ExpenseItem.objects.get(name="Milk")

    def post(self, **cols):
        data = {"date": cols.pop("date", today().isoformat())}
        data.update(cols)
        return self.client.post("/expenses/", data)

    def test_defaults_to_today(self):
        r = self.client.get("/expenses/")
        self.assertContains(r, f'value="{today().isoformat()}"')
        self.assertContains(r, "Milk")

    def test_multi_row_save_with_new_item_and_blank_row(self):
        r = self.post(
            item=[str(self.milk.pk), "__new__", ""],
            qty=["4", "2", ""],
            amount=["240", "100", ""],
            mode=["cash", "upi", "cash"],
            note=["", "", ""],
            new_name=["", " ice  cubes ", ""],
            new_unit=["L", "bag", "nos"],
            new_category=["other", "beverages", "other"],
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(DailyExpense.objects.count(), 2)
        ice = ExpenseItem.objects.get(name="ice cubes")
        self.assertEqual((ice.unit, ice.category), ("bag", "beverages"))
        e = DailyExpense.objects.get(item=self.milk)
        self.assertEqual((e.quantity, e.amount, e.created_by), (Decimal("4"), Decimal("240"), self.user))

    def test_previous_date(self):
        yday = today() - timedelta(days=1)
        self.post(date=yday.isoformat(), item=[str(self.milk.pk)], qty=["1"], amount=["60"], mode=["cash"])
        self.assertEqual(DailyExpense.objects.get().date, yday)

    def test_one_bad_row_saves_nothing(self):
        r = self.post(item=[str(self.milk.pk), str(self.milk.pk)], qty=["1", "1"], amount=["60", ""], mode=["cash", "cash"])
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Enter the amount paid")
        self.assertEqual(DailyExpense.objects.count(), 0)

    def test_future_date_rejected(self):
        r = self.post(date=(today() + timedelta(days=2)).isoformat(), item=[str(self.milk.pk)], amount=["60"])
        self.assertEqual(DailyExpense.objects.count(), 0)
        self.assertContains(r, "future")

    def test_history_and_csv(self):
        DailyExpense.objects.create(item=self.milk, quantity=2, amount=120)
        r = self.client.get("/expenses/history/?view=month")
        self.assertContains(r, "₹120")
        r = self.client.get("/expenses/history/?view=month&format=csv")
        self.assertIn(b"Milk", r.content)

    def test_import_items(self):
        csv = b"Item,Unit,Category\nMilk,L,Dairy\nPaneer,kg,dairy\nGas Cylinder,cylinder,Gas & fuel\n,,\n"
        self.client.post("/expenses/items/import/", {"file": SimpleUploadedFile("items.csv", csv)})
        self.assertEqual(ExpenseItem.objects.get(name="Paneer").category, "dairy")
        self.assertEqual(ExpenseItem.objects.get(name="Gas Cylinder").unit, "cyl")
        self.assertEqual(ExpenseItem.objects.filter(name__iexact="milk").count(), 1)
