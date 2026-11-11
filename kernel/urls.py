from django.urls import path

from . import pages_view

app_name = "kernel"
urlpatterns = [
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/", pages_view.page, name="page"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/i/<slug:key>/", pages_view.import_file, name="import"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/x/<slug:key>/", pages_view.export_file, name="export"),
    path("internal/runner/sql/", pages_view.runner_sql, name="runner_sql"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/f/<slug:form>/", pages_view.submit, name="form"),
]
