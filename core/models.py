from django.conf import settings
from django.db import models


class Payer(models.Model):
    """Who put the money in: Eatalley's own account/cash, or a partner paying personally."""

    name = models.CharField(max_length=60, unique=True)
    is_business = models.BooleanField(
        default=False, help_text="Eatalley's own money (not a partner to be reimbursed)"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_business", "name"]

    def __str__(self):
        return self.name

    @classmethod
    def default(cls):
        return cls.objects.filter(is_business=True, is_active=True).first()


class TrackedModel(models.Model):
    """Records who entered a row and when."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Set on rows loaded by a bulk import (e.g. the Google Sheet) so they can be undone together.
    source = models.CharField(max_length=40, blank=True, db_index=True, editable=False)

    class Meta:
        abstract = True


def paid_by_field():
    return models.ForeignKey(
        Payer, null=True, blank=True, on_delete=models.PROTECT, related_name="+", verbose_name="Paid by"
    )
