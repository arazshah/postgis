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
    path("dashboard/<int:pk>/maps/<int:map_id>/layers/", views.layer_add, name="layer_add"),
    path("dashboard/<int:pk>/maps/<int:map_id>/layers/<int:layer_id>/remove/", views.layer_remove,
         name="layer_remove"),
    path("dashboard/<int:pk>/maps/<int:map_id>/layers/<int:layer_id>/stats/", views.layer_stats,
         name="layer_stats"),
    # آدرس‌های عمومی
    path("maps/<slug:slug>/", views.public_map, name="map"),
    path("maps/<slug:slug>/embed/", views.embed_map, name="embed"),
    path("maps/<slug:slug>/t/<int:layer_id>/<int:z>/<int:x>/<int:y>.mvt", views.tile, name="tile"),
]
