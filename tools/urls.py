from django.urls import path

from . import views

app_name = "tools"
urlpatterns = [
    path("dashboard/<int:pk>/tools/", views.index, name="page"),
    path("dashboard/<int:pk>/tools/<slug:key>/", views.detail, name="detail"),
]
