from django.urls import path

from . import views

app_name = "payroll"

urlpatterns = [
    path("", views.index, name="index"),
    path("add/", views.staff_add, name="staff_add"),
    path("<int:pk>/edit/", views.staff_edit, name="staff_edit"),
    path("pay/", views.payment_form, name="pay"),
    path("pay/all/", views.pay_all, name="pay_all"),
    path("payments/<int:pk>/edit/", views.payment_form, name="payment_edit"),
    path("payments/<int:pk>/delete/", views.payment_delete, name="payment_delete"),
    path("leave/", views.leave_form, name="leave"),
    path("leave/<int:pk>/edit/", views.leave_form, name="leave_edit"),
    path("leave/<int:pk>/delete/", views.leave_delete, name="leave_delete"),
]
