from django.contrib import admin

from .models import Purchase, PurchaseLine, Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "supplies", "phone", "is_active"]


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["bill_date", "vendor", "bill_number", "total", "is_paid", "created_by"]
    list_filter = ["vendor", "is_paid", "category"]
    search_fields = ["bill_number", "notes"]
    date_hierarchy = "bill_date"
    inlines = [PurchaseLineInline]
