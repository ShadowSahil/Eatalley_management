from django.urls import path

from . import views

app_name = "opening"

urlpatterns = [
    path("", views.index, name="index"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/delete/", views.delete, name="delete"),
]
