from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("config/", views.config, name="config"),
    path("ask/", views.ask, name="ask"),
    path("feedback/", views.feedback, name="feedback"),
]
