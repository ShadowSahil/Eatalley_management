from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password/",
        auth_views.PasswordChangeView.as_view(success_url="/"),
        name="password_change",
    ),
    path("admin/", admin.site.urls),
    path("sales/", include("sales.urls")),
    path("expenses/", include("expenses.urls")),
    path("inventory/", include("inventory.urls")),
    path("staff/", include("payroll.urls")),
    path("pnl/", include("reports.urls")),
    path("opening/", include("opening.urls")),
    path("", include("core.urls")),
]
