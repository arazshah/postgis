from django.urls import path

from . import api, ows, ows_views, views

app_name = "publish"

urlpatterns = [
    path("dashboard/<int:pk>/publish/", views.manage, name="manage"),
    path("dashboard/<int:pk>/publish/table/", views.publish_table, name="publish_table"),
    path("dashboard/<int:pk>/publish/layer/<int:layer_id>/", views.update_layer, name="update_layer"),
    path("dashboard/<int:pk>/publish/keys/", views.create_key, name="create_key"),
    path("dashboard/<int:pk>/publish/keys/<int:key_id>/revoke/", views.revoke_key, name="revoke_key"),
    path("dashboard/<int:pk>/publish/layer/<int:layer_id>/map/", views.map_builder, name="map_builder"),
    path("dashboard/<int:pk>/publish/layer/<int:layer_id>/map/stats/", views.map_stats, name="map_stats"),
    path("dashboard/<int:pk>/publish/ows/", ows_views.index, name="ows"),
    path("dashboard/<int:pk>/publish/ows/saved/", ows_views.import_saved, name="ows_import_saved"),
    path("dashboard/<int:pk>/publish/ows/<int:project_id>/", ows_views.detail, name="ows_detail"),
    path("dashboard/<int:pk>/publish/ows/<int:project_id>/refresh/", ows_views.refresh, name="ows_refresh"),
    path("dashboard/<int:pk>/publish/ows/<int:project_id>/delete/", ows_views.delete, name="ows_delete"),
    # آدرس‌های عمومی
    path("ows/<slug:slug>/", ows.ows, name="ows_service"),
    path("m/<slug:slug>/", views.public_map, name="map"),
    path("m/<slug:slug>/embed/", views.embed_map, name="embed"),
    path("tiles/<slug:slug>/<int:z>/<int:x>/<int:y>.mvt", api.tile, name="tile"),
    path("tiles/<slug:slug>/<int:z>/<int:x>/<int:y>.pbf", api.tile),
    path("tiles/<slug:slug>.json", api.tilejson, name="tilejson"),
    path("ogc/<slug:slug>/", api.landing, name="ogc"),
    path("ogc/<slug:slug>/conformance", api.conformance, name="ogc_conformance"),
    path("ogc/<slug:slug>/collections", api.collections, name="ogc_collections"),
    path("ogc/<slug:slug>/collections/<str:cid>", api.collection, name="ogc_collection"),
    path("ogc/<slug:slug>/collections/<str:cid>/items", api.items, name="ogc_items"),
    path("ogc/<slug:slug>/collections/<str:cid>/items/<str:fid>", api.item, name="ogc_item"),
]
