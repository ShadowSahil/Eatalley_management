from django.contrib import admin

from .models import SalaryPayment, Staff


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ["name", "role", "monthly_salary", "is_active"]


@admin.register(SalaryPayment)
class SalaryPaymentAdmin(admin.ModelAdmin):
    list_display = ["month", "staff", "kind", "amount", "paid_on"]
    list_filter = ["kind", "staff"]
