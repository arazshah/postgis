from django.urls import path

from . import views

app_name = "live"
urlpatterns = [
    path("", views.index, name="index"),
    path("<int:pk>/", views.projects, name="projects"),
    path("<int:pk>/<int:map_id>/", views.studio, name="studio"),
    path("<int:pk>/table/", views.table, name="table"),
    path("<int:pk>/tool/", views.tool, name="tool"),
    path("<int:pk>/tool/<int:job_id>/", views.tool_status, name="tool_status"),
]
