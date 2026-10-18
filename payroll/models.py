from django.db import models

from core.models import TrackedModel, paid_by_field
from core.periods import today
from expenses.models import PAYMENT_MODES


class Staff(models.Model):
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=60, blank=True, help_text="Chef, helper, delivery, manager...")
    phone = models.CharField(max_length=20, blank=True)
    monthly_salary = models.DecimalField(max_digits=10, decimal_places=2)
    joined_on = models.DateField(null=True, blank=True)
    left_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-is_active", "name"]
        verbose_name_plural = "staff"

    def __str__(self):
        return self.name

    def employed_during(self, start, end):
        if self.joined_on and self.joined_on > end:
            return False
        if self.left_on and self.left_on < start:
            return False
        return True


class SalaryPayment(TrackedModel):
    KINDS = [
        ("salary", "Salary"),
        ("advance", "Advance"),
        ("bonus", "Bonus / incentive"),
    ]

    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, related_name="payments")
    month = models.DateField(help_text="The salary month this payment counts towards (stored as the 1st)")
    kind = models.CharField(max_length=10, choices=KINDS, default="salary")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_on = models.DateField(default=today)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODES, default="cash", blank=True)
    paid_by = paid_by_field()
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-month", "staff__name"]

    def save(self, *args, **kwargs):
        self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.staff} {self.month:%b %Y} ₹{self.amount}"
