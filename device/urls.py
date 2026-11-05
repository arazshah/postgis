from django.urls import path

from . import views

app_name = "device"

urlpatterns = [
    path("password/", views.password_view, name="password"),
    path("users/", views.users_view, name="users"),
    path("system/", views.system_view, name="system"),
    path("time/", views.time_view, name="time"),
]
