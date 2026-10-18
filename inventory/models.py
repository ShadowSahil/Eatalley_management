from django.db import models
from django.db.models import Q

from core.models import TrackedModel, paid_by_field
from core.periods import today
from expenses.models import PAYMENT_MODES


class InventoryCategory(models.TextChoices):
    DAIRY = "dairy", "Cheese, butter & dairy"
    FLOUR = "flour", "Flour & bakery"
    VEGETABLES = "vegetables", "Vegetables"
    SAUCES = "sauces", "Sauces & grocery"
    MEAT = "meat", "Meat & toppings"
    PACKAGING = "packaging", "Packaging"
    BEVERAGES = "beverages", "Beverages"
    OTHER = "other", "Other"


class Vendor(models.Model):
    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=20, choices=InventoryCategory.choices, default=InventoryCategory.OTHER)
    supplies = models.CharField(max_length=200, blank=True, help_text="What we usually buy from them")
    match_keywords = models.CharField(
        max_length=200,
        blank=True,
        help_text="Comma-separated words that appear on their bills, used to recognise uploaded PDFs",
    )
    phone = models.CharField(max_length=20, blank=True)
    gstin = models.CharField("GSTIN", max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def keywords(self):
        words = [w.strip().lower() for w in self.match_keywords.split(",") if w.strip()]
        return words or [self.name.lower()]


class Purchase(TrackedModel):
    """One vendor bill."""

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="purchases")
    bill_date = models.DateField(default=today, db_index=True)
    bill_number = models.CharField(max_length=50, blank=True)
    category = models.CharField(max_length=20, choices=InventoryCategory.choices, default=InventoryCategory.OTHER)
    tax_amount = models.DecimalField("GST / tax", max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField("Bill total", max_digits=12, decimal_places=2)
    bill_file = models.FileField(upload_to="inventory/bills/%Y/%m/", blank=True)
    is_paid = models.BooleanField("Paid", default=False)
    paid_on = models.DateField(null=True, blank=True)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODES, blank=True)
    paid_by = paid_by_field()
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-bill_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["vendor", "bill_number"],
                condition=~Q(bill_number=""),
                name="purchase_unique_bill_per_vendor",
                violation_error_message="This bill number is already entered for this vendor.",
            )
        ]

    def __str__(self):
        return f"{self.vendor} {self.bill_number or self.bill_date} ₹{self.total}"


class PurchaseLine(models.Model):
    """Optional breakdown of what was on the bill (cheese 10 kg, butter 5 kg...)."""

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=150)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=10, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return self.description
