from django.urls import path

from . import pages_view

app_name = "kernel"
urlpatterns = [
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/", pages_view.page, name="page"),
    path("internal/runner/sql/", pages_view.runner_sql, name="runner_sql"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/f/<slug:form>/", pages_view.submit, name="form"),
]
