from django.urls import path

from . import views
from .paid_by import paid_by_view

app_name = "reports"

urlpatterns = [
    path("", views.pnl_view, name="pnl"),
    path("paid-by/", paid_by_view, name="paid_by"),
]
