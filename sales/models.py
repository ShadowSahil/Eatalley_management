from django.db import models

from core.models import TrackedModel


class SalesUpload(TrackedModel):
    REPORT_TYPES = [
        ("orders", "Orders / invoices report"),
        ("items", "Item-wise report"),
    ]

    file = models.FileField(upload_to="sales/uploads/%Y/%m/")
    original_name = models.CharField(max_length=255)
    report_type = models.CharField(max_length=10, choices=REPORT_TYPES)
    start_date = models.DateField(null=True)
    end_date = models.DateField(null=True)
    rows_imported = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    log = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_name


class SaleOrder(models.Model):
    """One Petpooja invoice."""

    upload = models.ForeignKey(SalesUpload, null=True, blank=True, on_delete=models.CASCADE, related_name="orders")
    invoice_no = models.CharField(max_length=50, blank=True)
    date = models.DateField(db_index=True)
    time = models.TimeField(null=True, blank=True)
    order_type = models.CharField(max_length=50, blank=True)
    source = models.CharField(max_length=50, blank=True, help_text="Area / channel, e.g. Zomato, Swiggy")
    payment_mode = models.CharField(max_length=50, blank=True)
    customer_name = models.CharField(max_length=100, blank=True)
    customer_phone = models.CharField(max_length=15, blank=True, db_index=True, help_text="Digits only; Indian numbers without +91")
    status = models.CharField(max_length=30, blank=True)
    is_cancelled = models.BooleanField(default=False)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    container_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["-date", "-time"]

    def __str__(self):
        return f"{self.invoice_no} {self.date} ₹{self.total}"


class SaleItemLine(models.Model):
    """Item-wise sales: one item on one day (or on one invoice, if the report has invoices)."""

    upload = models.ForeignKey(SalesUpload, null=True, blank=True, on_delete=models.CASCADE, related_name="items")
    date = models.DateField(db_index=True)
    invoice_no = models.CharField(max_length=50, blank=True)
    item_name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["-date", "item_name"]

    def __str__(self):
        return f"{self.date} {self.item_name} x{self.quantity}"


class SalePayment(models.Model):
    """How an order was paid. Usually one row; several for Petpooja part payments."""

    order = models.ForeignKey(SaleOrder, on_delete=models.CASCADE, related_name="payments")
    mode = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.mode} ₹{self.amount}"
