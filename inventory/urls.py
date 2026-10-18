from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.purchase_list, name="list"),
    path("add/", views.purchase_form, name="add"),
    path("scan/", views.purchase_scan, name="scan"),
    path("<int:pk>/edit/", views.purchase_form, name="edit"),
    path("<int:pk>/delete/", views.purchase_delete, name="delete"),
    path("<int:pk>/attach/", views.purchase_attach, name="attach"),
    path("<int:pk>/paid/", views.purchase_mark_paid, name="mark_paid"),
    path("vendors/", views.vendors, name="vendors"),
    path("vendors/<int:pk>/edit/", views.vendor_edit, name="vendor_edit"),
]
