from django.urls import path

from . import views

app_name = "analysis"
urlpatterns = [
    path("dashboard/<int:pk>/analysis/", views.page, name="page"),
    path("dashboard/<int:pk>/analysis/status/", views.status, name="status"),
]
