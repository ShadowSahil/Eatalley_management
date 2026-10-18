from django.contrib import admin

from .models import DailyExpense, ExpenseItem


@admin.register(ExpenseItem)
class ExpenseItemAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "unit", "is_active"]
    list_filter = ["category", "is_active"]
    search_fields = ["name"]


@admin.register(DailyExpense)
class DailyExpenseAdmin(admin.ModelAdmin):
    list_display = ["date", "item", "quantity", "amount", "payment_mode", "created_by"]
    list_filter = ["date", "payment_mode", "item__category"]
    search_fields = ["item__name", "note"]
    date_hierarchy = "date"
