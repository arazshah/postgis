from django.urls import path

from . import views

app_name = "notifications"
urlpatterns = [
    path("notifications/poll/", views.poll, name="poll"),
    path("notifications/read/", views.read, name="read"),
    path("notifications/log/", views.log, name="log"),
]
