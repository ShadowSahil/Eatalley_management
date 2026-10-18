from django.urls import path

from . import views

app_name = "expenses"

urlpatterns = [
    path("", views.entry, name="entry"),
    path("history/", views.expense_list, name="list"),
    path("<int:pk>/edit/", views.expense_edit, name="edit"),
    path("<int:pk>/delete/", views.expense_delete, name="delete"),
    path("items/", views.items, name="items"),
    path("items/import/", views.items_import, name="items_import"),
    path("items/<int:pk>/edit/", views.item_edit, name="item_edit"),
]
