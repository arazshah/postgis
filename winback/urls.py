from django.urls import path

from . import views

app_name = "winback"
urlpatterns = [
    path("<str:code>/", views.go, name="go"),
    path("<str:code>/stop/", views.stop, name="stop"),
]
