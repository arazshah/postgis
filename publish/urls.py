from django.urls import path

from . import api, views

app_name = "publish"

urlpatterns = [
    path("dashboard/<int:pk>/publish/", views.manage, name="manage"),
    path("dashboard/<int:pk>/publish/table/", views.publish_table, name="publish_table"),
    path("dashboard/<int:pk>/publish/layer/<int:layer_id>/", views.update_layer, name="update_layer"),
    path("dashboard/<int:pk>/publish/keys/", views.create_key, name="create_key"),
    path("dashboard/<int:pk>/publish/keys/<int:key_id>/revoke/", views.revoke_key, name="revoke_key"),
    # آدرس‌های عمومی
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
