from django.urls import path

from . import user_views, views

app_name = "iranmap"
urlpatterns = [
    path("basemap/style.json", views.style, name="style"),
    path("basemap/<int:z>/<int:x>/<int:y>.mvt", views.tile, name="tile"),
    path("dashboard/<int:pk>/iran-data/", user_views.ready_data, name="ready"),
    path("dashboard/iran-data/areas/", user_views.areas, name="areas"),
    path("dashboard/<int:pk>/iran-data/status/", user_views.status, name="status"),
]
