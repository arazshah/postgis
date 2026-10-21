from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("<slug:slug>/", views.go, name="go"),
]
