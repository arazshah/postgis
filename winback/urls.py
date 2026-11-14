from django.urls import path

from . import views

app_name = "winback"
urlpatterns = [
    path("stop/<str:code>/", views.stop, name="stop_short"),
    path("invite/<str:code>/", views.invite, name="invite"),
    path("<str:code>/", views.go, name="go"),
    path("<str:code>/stop/", views.stop, name="stop"),
]
