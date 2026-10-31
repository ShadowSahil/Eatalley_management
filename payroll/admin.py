from django.contrib import admin

from .models import Leave, SalaryPayment, Staff


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ["name", "role", "monthly_salary", "leave_allowance", "is_active"]


@admin.register(SalaryPayment)
class SalaryPaymentAdmin(admin.ModelAdmin):
    list_display = ["month", "staff", "kind", "amount", "paid_on"]
    list_filter = ["kind", "staff"]


@admin.register(Leave)
class LeaveAdmin(admin.ModelAdmin):
    list_display = ["staff", "start", "end", "half_day", "kind", "note"]
    list_filter = ["kind", "staff"]
    date_hierarchy = "start"
