from django.db import models
from django.db.models.functions import Lower

from core.models import TrackedModel, paid_by_field
from core.periods import today
from expenses.models import PAYMENT_MODES


class FixedCostHead(models.Model):
    """A cost that comes every month: shop rent, electricity bill, staff room rent..."""

    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True, help_text="Untick to stop expecting it every month.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [Lower("name")]
        constraints = [models.UniqueConstraint(Lower("name"), name="fixed_cost_head_name_ci_unique")]

    def __str__(self):
        return self.name


class FixedCost(TrackedModel):
    """One payment towards a fixed cost, counted in the P&L for the month it is for."""

    head = models.ForeignKey(FixedCostHead, on_delete=models.PROTECT, related_name="payments", verbose_name="Type")
    month = models.DateField(db_index=True, help_text="Month this cost is for")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField(default=today)
    payment_mode = models.CharField("Mode", max_length=10, choices=PAYMENT_MODES, blank=True)
    paid_by = paid_by_field()
    note = models.CharField(max_length=200, blank=True)
    bill_file = models.FileField(upload_to="fixed/bills/%Y/%m/", blank=True)

    class Meta:
        ordering = ["-month", "-paid_on"]

    def __str__(self):
        return f"{self.head} {self.month:%b %Y} ₹{self.amount}"

    def save(self, *args, **kwargs):
        self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)
