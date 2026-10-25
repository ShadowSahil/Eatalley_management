from django.urls import path

from . import views

app_name = "fixedcosts"

urlpatterns = [
    path("", views.index, name="index"),
    path("add/", views.cost_form, name="add"),
    path("<int:pk>/edit/", views.cost_form, name="edit"),
    path("<int:pk>/delete/", views.cost_delete, name="delete"),
    path("types/add/", views.head_add, name="head_add"),
    path("types/<int:pk>/edit/", views.head_edit, name="head_edit"),
]
