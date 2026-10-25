from django.urls import path, re_path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("team/", views.team, name="team"),
    path("team/<int:pk>/toggle/", views.team_toggle, name="team_toggle"),
    path("team/<int:pk>/password/", views.team_password, name="team_password"),
    re_path(r"^media/(?P<path>.*)$", views.media, name="media"),
]
