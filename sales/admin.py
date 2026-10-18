from django.contrib import admin

from .models import SaleItemLine, SaleOrder, SalesUpload


@admin.register(SalesUpload)
class SalesUploadAdmin(admin.ModelAdmin):
    list_display = ["original_name", "report_type", "start_date", "end_date", "rows_imported", "created_by", "created_at"]


@admin.register(SaleOrder)
class SaleOrderAdmin(admin.ModelAdmin):
    list_display = ["date", "invoice_no", "order_type", "payment_mode", "total", "is_cancelled"]
    list_filter = ["order_type", "payment_mode", "is_cancelled"]
    search_fields = ["invoice_no"]
    date_hierarchy = "date"


@admin.register(SaleItemLine)
class SaleItemLineAdmin(admin.ModelAdmin):
    list_display = ["date", "item_name", "category", "quantity", "amount"]
    search_fields = ["item_name"]
    date_hierarchy = "date"
