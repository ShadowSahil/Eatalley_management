from django.contrib import admin

from .models import FixedCost, FixedCostHead


@admin.register(FixedCostHead)
class FixedCostHeadAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]


@admin.register(FixedCost)
class FixedCostAdmin(admin.ModelAdmin):
    list_display = ["month", "head", "amount", "paid_on", "payment_mode", "paid_by", "note"]
    list_filter = ["head", "paid_by"]
    search_fields = ["note"]
    date_hierarchy = "month"
