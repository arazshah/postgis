from django.urls import path

from . import pages_view

app_name = "kernel"
urlpatterns = [
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/", pages_view.page, name="page"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/i/<slug:key>/", pages_view.import_file, name="import"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/x/<slug:key>/", pages_view.export_file, name="export"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/r/<slug:key>/<int:rid>/", pages_view.record_edit, name="record_edit"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/r/<slug:key>/<int:rid>/delete/", pages_view.record_delete, name="record_delete"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/report/<slug:key>.pdf", pages_view.report_pdf, name="report"),
    path("ingest/", pages_view.ingest_receive, name="ingest"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/s/<slug:key>/", pages_view.source_save, name="source_save"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/s/<slug:key>/run/", pages_view.source_run, name="source_run"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/n/<slug:key>/", pages_view.ingest_token_create, name="ingest_token"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/n/<slug:key>/<int:token_id>/revoke/", pages_view.ingest_token_revoke,
         name="ingest_revoke"),
    path("internal/runner/sql/", pages_view.runner_sql, name="runner_sql"),
    path("dashboard/<int:pk>/p/<slug:plugin>/<slug:page>/f/<slug:form>/", pages_view.submit, name="form"),
]
