from django.contrib import admin

from .models import OpeningCost


@admin.register(OpeningCost)
class OpeningCostAdmin(admin.ModelAdmin):
    list_display = ["date", "amount", "category", "paid_to", "description", "paid_by"]
    list_filter = ["category", "paid_by"]
    search_fields = ["paid_to", "description"]
    date_hierarchy = "date"
