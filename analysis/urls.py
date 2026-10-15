from django.urls import path

from . import views

app_name = "analysis"
urlpatterns = [path("dashboard/<int:pk>/analysis/", views.page, name="page")]
