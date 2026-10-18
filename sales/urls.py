from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("upload/", views.upload, name="upload"),
    path("upload/<int:pk>/delete/", views.upload_delete, name="upload_delete"),
]
