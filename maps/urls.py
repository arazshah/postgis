from django.urls import path

from . import views

app_name = "maps"

urlpatterns = [
    path("dashboard/<int:pk>/maps/", views.index, name="index"),
    path("dashboard/<int:pk>/maps/new/", views.create, name="create"),
    path("dashboard/<int:pk>/maps/add-table/", views.add_table, name="add_table"),
    path("dashboard/<int:pk>/maps/quick/", views.quick, name="quick"),
    path("dashboard/<int:pk>/maps/preview/<str:schema>/<str:table>/<int:z>/<int:x>/<int:y>.mvt", views.preview_tile,
         name="preview_tile"),
    path("dashboard/<int:pk>/maps/<int:map_id>/", views.composer, name="composer"),
    path("dashboard/<int:pk>/maps/<int:map_id>/delete/", views.delete, name="delete"),
    path("dashboard/<int:pk>/maps/<int:map_id>/duplicate/", views.duplicate, name="duplicate"),
    path("dashboard/<int:pk>/maps/<int:map_id>/qgis/", views.qgis_project, name="qgis"),
    path("dashboard/<int:pk>/maps/<int:map_id>/ows/", views.publish_ows, name="publish_ows"),
    path("dashboard/<int:pk>/maps/<int:map_id>/charts/preview/", views.chart_preview, name="chart_preview"),
    path("dashboard/<int:pk>/maps/<int:map_id>/layers/", views.layer_add, name="layer_add"),
    path("dashboard/<int:pk>/maps/<int:map_id>/layers/<int:layer_id>/remove/", views.layer_remove,
         name="layer_remove"),
    path("dashboard/<int:pk>/maps/<int:map_id>/layers/<int:layer_id>/extent/", views.layer_extent,
         name="layer_extent"),
    path("dashboard/<int:pk>/maps/<int:map_id>/layers/<int:layer_id>/stats/", views.layer_stats,
         name="layer_stats"),
    # آدرس‌های عمومی
    path("maps/<slug:slug>/", views.public_map, name="map"),
    path("maps/<slug:slug>/embed/", views.embed_map, name="embed"),
    path("maps/<slug:slug>/present/", views.present, name="present"),
    path("maps/<slug:slug>/print/", views.print_map, name="print"),
    path("maps/<slug:slug>/compare/", views.compare, name="compare"),
    path("maps/<slug:slug>/c/<int:chart_id>.json", views.chart_data, name="chart_data"),
    path("maps/<slug:slug>/t/<int:layer_id>/<int:z>/<int:x>/<int:y>.mvt", views.tile, name="tile"),
]
