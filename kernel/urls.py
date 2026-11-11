from django.urls import path

from . import pages_view

app_name = "kernel"
urlpatterns = [
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/", pages_view.page, name="page"),
]
