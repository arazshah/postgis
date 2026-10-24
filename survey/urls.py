from django.urls import path

from . import views

app_name = "survey"

urlpatterns = [
    path("dashboard/<int:pk>/survey/", views.index, name="index"),
    path("dashboard/<int:pk>/survey/new/", views.create, name="create"),
    path("dashboard/<int:pk>/survey/sw.js", views.service_worker, name="sw"),
    path("dashboard/<int:pk>/survey/<int:project_id>/", views.studio, name="studio"),
    path("dashboard/<int:pk>/survey/<int:project_id>/archive/", views.archive, name="archive"),
    path("dashboard/<int:pk>/survey/<int:project_id>/data/", views.project_data, name="data"),
    path("dashboard/<int:pk>/survey/<int:project_id>/sync/", views.project_sync, name="sync"),
    path("dashboard/<int:pk>/survey/<int:project_id>/import/", views.project_import, name="import"),
    path("dashboard/<int:pk>/survey/<int:project_id>/cogo/", views.project_cogo, name="cogo"),
    path("dashboard/<int:pk>/survey/<int:project_id>/export/<str:fmt>/", views.export, name="export"),
    path("api/v1/survey/<slug:slug>/sync/", views.api_sync, name="api_sync"),
]
