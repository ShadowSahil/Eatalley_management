from django.db import models
from django.db.models.functions import Lower

from core.models import TrackedModel, paid_by_field
from core.periods import today

UNIT_CHOICES = [
    ("kg", "kg"),
    ("g", "g"),
    ("L", "litre"),
    ("ml", "ml"),
    ("pcs", "pcs"),
    ("pkt", "packet"),
    ("btl", "bottle"),
    ("crate", "crate"),
    ("box", "box"),
    ("dozen", "dozen"),
    ("bag", "bag"),
    ("cyl", "cylinder"),
    ("nos", "nos"),
]

PAYMENT_MODES = [
    ("cash", "Cash"),
    ("upi", "UPI"),
    ("card", "Card"),
    ("bank", "Bank transfer"),
    ("credit", "Pay later"),
]


class ExpenseCategory(models.TextChoices):
    DAIRY = "dairy", "Dairy"
    BEVERAGES = "beverages", "Beverages"
    VEG_FRUIT = "veg_fruit", "Vegetables & fruits"
    GROCERY = "grocery", "Grocery"
    GAS_FUEL = "gas_fuel", "Gas & fuel"
    PACKAGING = "packaging", "Packaging"
    CLEANING = "cleaning", "Cleaning & hygiene"
    REPAIRS = "repairs", "Repairs & maintenance"
    UTILITIES = "utilities", "Electricity & utilities"
    RENT = "rent", "Rent"
    TRANSPORT = "transport", "Transport & delivery"
    STAFF = "staff", "Staff food & welfare"
    MARKETING = "marketing", "Marketing"
    ADMIN = "admin", "Admin, fees & subscriptions"
    GST = "gst", "GST paid to government"
    OTHER = "other", "Other"


class ExpenseItem(models.Model):
    """Something we pay for day to day: milk, cold drinks, coconut water, ice..."""

    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=ExpenseCategory.choices, default=ExpenseCategory.OTHER)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default="nos")
    is_active = models.BooleanField(default=True, help_text="Untick to hide it from the dropdown.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [Lower("name")]
        constraints = [models.UniqueConstraint(Lower("name"), name="expense_item_name_ci_unique")]

    def __str__(self):
        return self.name


class DailyExpense(TrackedModel):
    date = models.DateField(default=today, db_index=True)
    item = models.ForeignKey(ExpenseItem, on_delete=models.PROTECT, related_name="expenses")
    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_mode = models.CharField("Mode", max_length=10, choices=PAYMENT_MODES, default="cash", blank=True)
    paid_by = paid_by_field()
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.date} {self.item} ₹{self.amount}"

    @property
    def rate(self):
        if self.quantity:
            return self.amount / self.quantity
        return None
