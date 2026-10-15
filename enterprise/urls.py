from django.urls import path

from . import views

app_name = "enterprise"
urlpatterns = [
    path("dashboard/<int:pk>/enterprise/", views.page, name="page"),
    path("raster/<slug:slug>/<int:z>/<int:x>/<int:y>.png", views.raster_tile, name="raster_tile"),
    path("raster/<slug:slug>.json", views.raster_tilejson, name="raster_tilejson"),
    path("r/<slug:slug>/", views.raster_view, name="raster_view"),
]
