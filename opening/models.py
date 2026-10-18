from django.db import models

from core.models import TrackedModel, paid_by_field
from core.periods import today


class OpeningCategory(models.TextChoices):
    EQUIPMENT = "equipment", "Equipment"
    INTERIOR = "interior", "Interior & fit-out"
    SHOP = "shop", "Shop (rent deposit, lease)"
    INVENTORY = "inventory", "Starting inventory & packaging"
    MARKETING = "marketing", "Marketing & launch"
    FOOD_TASTING = "food_tasting", "Food tasting & trials"
    MISC = "misc", "Misc"


class OpeningCost(TrackedModel):
    """One-time spend on setting up the café (oven, furniture, fit-out...). Not part of the P&L."""

    date = models.DateField(default=today, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    category = models.CharField(max_length=20, choices=OpeningCategory.choices, default=OpeningCategory.EQUIPMENT)
    paid_to = models.CharField("Paid to", max_length=100, blank=True, help_text="Shop, vendor or person")
    description = models.CharField(max_length=200, blank=True)
    paid_by = paid_by_field()
    bill_file = models.FileField(upload_to="opening/bills/%Y/%m/", blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.date} {self.description or self.paid_to} ₹{self.amount}"
